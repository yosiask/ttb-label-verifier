#!/usr/bin/env python3
"""Application-only deployment onto Azure resources that already exist.

The infrastructure (resource group, Azure OpenAI resource and model deployment, container
registry, Container Apps environment and app, managed identity and role assignments) is
provisioned separately by the infrastructure owner. This tool creates nothing. It:

  check   read-only: finds the resources in the resource group and checks that the app can
          run on them (model, auth, identity roles, registry pull, ingress, sizing, quota)
  deploy  check, then build the image in the existing registry (az acr build), point the
          existing container app at it with the app settings, and smoke-test /api/health
          and /api/config. It never calls /api/verify, so it starts no model inference.

    python deploy/azure/app_deploy.py check  --resource-group rg-ttb-label-verifier
    python deploy/azure/app_deploy.py deploy --resource-group rg-ttb-label-verifier --confirm

Resource names are discovered when the group holds exactly one of each kind; pass
--app/--registry/--openai/--model-deployment to choose otherwise. Needs the Azure CLI,
signed in (az login), with read access to the group; deploy also needs AcrPush on the
registry (or Contributor) and Container Apps Contributor on the app.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[2]
IMAGE_REPO = "ttb-label-verifier"

EXPECTED_LOCATION = "eastus2"
EXPECTED_MODEL, EXPECTED_MODEL_VERSION = "gpt-4.1-mini", "2025-04-14"
# Data-plane roles that let the app call the model. Owner/Contributor do not include data actions.
OPENAI_ROLES_LEAST = {"Cognitive Services OpenAI User"}
OPENAI_ROLES_BROADER = {"Cognitive Services OpenAI Contributor", "Cognitive Services User", "Azure AI User",
                        "Azure AI Developer"}
ACR_ROLES_LEAST = {"AcrPull", "Container Registry Repository Reader"}
ACR_ROLES_BROADER = {"AcrPush", "Contributor", "Owner", "Container Registry Repository Writer"}

# Tokens Azure counts against tokens-per-minute for one label: about 2.5K for the image at
# 1600 px, about 0.6K of instructions and the max_tokens output budget (1000). Azure's estimate
# is approximate; recalibrate from the x-ratelimit-* response headers after the first real calls.
DEFAULT_TOKENS_PER_LABEL = 4500
QUOTA_HEADROOM = 0.8  # pace below the limit: Azure checks in 1-10 s windows, not per minute

APP_SETTINGS = {
    "EXTRACTOR": "auto",
    "MAX_UPLOAD_MB": "10",
    "CLOUD_DAILY_CAP": "1000",
    "RATE_LIMIT_PER_MINUTE": "120",
    "TRUSTED_PROXY_HOPS": "1",  # Container Apps ingress appends the client address
    "AZURE_TIMEOUT_S": "8",
    "AZURE_MAX_OUTPUT_TOKENS": "1000",
    "VISION_OCR_CROSSCHECK": "true",
}

PASS, INFO, WARN, FAIL = "PASS", "INFO", "WARN", "FAIL"


class AzError(RuntimeError):
    pass


def run_az(args: list[str]) -> Any:
    """Run an az command that prints JSON. Returns None when the resource does not exist."""
    proc = subprocess.run(["az", *args, "-o", "json"], capture_output=True, text=True)
    if proc.returncode != 0:
        err = proc.stderr.strip()
        if "ResourceNotFound" in err or "ResourceGroupNotFound" in err or "was not found" in err \
                or "could not be found" in err or "DeploymentNotFound" in err:
            return None
        raise AzError(f"az {' '.join(args[:3])} failed: {err.splitlines()[-1] if err else proc.returncode}")
    return json.loads(proc.stdout) if proc.stdout.strip() else None


@dataclass
class Finding:
    level: str
    item: str
    detail: str


@dataclass
class Plan:
    """What the checks found, and what deploy will use."""
    findings: list[Finding] = field(default_factory=list)
    app: str | None = None
    registry: str | None = None
    login_server: str | None = None
    endpoint: str | None = None
    model_deployment: str | None = None
    capacity_k: int | None = None
    max_replicas: int | None = None
    cpu: float | None = None
    target_port: int | None = None
    fqdn: str | None = None
    identity_client_id: str | None = None  # set when the app calls the model as a user-assigned identity

    def add(self, level: str, item: str, detail: str) -> None:
        self.findings.append(Finding(level, item, detail))

    @property
    def ok(self) -> bool:
        return not any(f.level == FAIL for f in self.findings)


def _pick(kind: str, items: list[dict], wanted: str | None, plan: Plan) -> dict | None:
    if wanted:
        match = [i for i in items if i["name"].lower() == wanted.lower()]
        if not match:
            plan.add(FAIL, kind, f"\"{wanted}\" not found in the resource group.")
        return match[0] if match else None
    if len(items) == 1:
        return items[0]
    if not items:
        plan.add(FAIL, kind, "none found in the resource group.")
    else:
        plan.add(FAIL, kind, f"{len(items)} found ({', '.join(i['name'] for i in items)}); choose one with a flag.")
    return None


def _roles_for(az: Callable, scope: str, principal_id: str) -> set[str]:
    assignments = az(["role", "assignment", "list", "--scope", scope, "--include-inherited"]) or []
    return {a.get("roleDefinitionName") for a in assignments if a.get("principalId") == principal_id}


def _role_finding(plan: Plan, item: str, roles: set[str], least: set[str], broader: set[str], need: str) -> None:
    if roles & least:
        plan.add(PASS, item, f"has {', '.join(sorted(roles & least))}.")
    elif roles & broader:
        plan.add(WARN, item, f"has {', '.join(sorted(roles & broader))}: works, but broader than {need}.")
    else:
        plan.add(FAIL, item, f"missing {need}.")


def pace_per_replica(capacity_k: int, max_replicas: int, tokens_per_label: int) -> int:
    """Cloud calls per minute per replica that keep all replicas inside the deployment's quota.
    gpt-4.1-mini Standard allows 1 request per minute per 1K TPM, so tokens are the tighter limit."""
    by_tokens = capacity_k * 1000 * QUOTA_HEADROOM / tokens_per_label
    by_requests = capacity_k * QUOTA_HEADROOM
    return max(1, math.floor(min(by_tokens, by_requests) / max(1, max_replicas)))


def check(az: Callable, rg: str, app: str | None = None, registry: str | None = None,
          openai_name: str | None = None, model_deployment: str | None = None,
          tokens_per_label: int = DEFAULT_TOKENS_PER_LABEL) -> Plan:
    plan = Plan()
    account = az(["account", "show"])
    plan.add(INFO, "Subscription", f"{account['name']} (signed in as {account.get('user', {}).get('name', '?')}).")

    group = az(["group", "show", "--name", rg])
    if group is None:
        plan.add(FAIL, "Resource group", f"{rg} does not exist yet (or you cannot read it).")
        return plan
    plan.add(PASS if group["location"] == EXPECTED_LOCATION else WARN, "Resource group",
             f"{rg} in {group['location']}" + ("" if group["location"] == EXPECTED_LOCATION else f" (plan: {EXPECTED_LOCATION})."))

    resources = az(["resource", "list", "--resource-group", rg]) or []
    of_type = lambda t: [r for r in resources if r["type"].lower() == t.lower()]  # noqa: E731

    # ---- Azure OpenAI resource and model deployment
    aoai_ref = _pick("Azure OpenAI resource", of_type("Microsoft.CognitiveServices/accounts"), openai_name, plan)
    aoai = None
    if aoai_ref:
        aoai = az(["cognitiveservices", "account", "show", "--resource-group", rg, "--name", aoai_ref["name"]])
        props = aoai.get("properties", {})
        plan.endpoint = props.get("endpoint")
        kind, sku = aoai.get("kind"), (aoai.get("sku") or {}).get("name")
        plan.add(PASS if kind in ("OpenAI", "AIServices") and sku == "S0" else FAIL, "Azure OpenAI resource",
                 f"{aoai_ref['name']}: kind {kind}, SKU {sku}, endpoint {plan.endpoint}.")
        if not props.get("customSubDomainName"):
            plan.add(FAIL, "Azure OpenAI auth", "no custom subdomain: managed-identity (Entra ID) sign-in needs one.")
        elif props.get("disableLocalAuth"):
            plan.add(PASS, "Azure OpenAI auth", "Entra ID only (API keys disabled); the app uses its managed identity.")
        else:
            plan.add(WARN, "Azure OpenAI auth", "API keys are enabled. The app does not use them; consider disableLocalAuth=true.")
        if props.get("publicNetworkAccess") == "Disabled":
            plan.add(FAIL, "Azure OpenAI network", "public network access is disabled; a Consumption app without a "
                                                   "virtual network cannot reach it.")

        deployments = az(["cognitiveservices", "account", "deployment", "list",
                          "--resource-group", rg, "--name", aoai_ref["name"]]) or []
        dep = _pick("Model deployment", deployments, model_deployment, plan)
        if dep:
            plan.model_deployment = dep["name"]
            model = dep.get("properties", {}).get("model", {})
            dsku = dep.get("sku") or {}
            plan.capacity_k = int(dsku.get("capacity") or 0)
            right_model = model.get("name") == EXPECTED_MODEL and model.get("version") == EXPECTED_MODEL_VERSION
            plan.add(PASS if right_model else WARN, "Model",
                     f"deployment \"{dep['name']}\": {model.get('name')} {model.get('version')}"
                     + ("" if right_model else f" (the app was built and tested for {EXPECTED_MODEL} {EXPECTED_MODEL_VERSION})."))
            if dsku.get("name") == "Standard":
                plan.add(PASS, "Deployment type", "regional Standard: pay per call, processed in the resource's region.")
            elif "Provisioned" in (dsku.get("name") or ""):
                plan.add(FAIL, "Deployment type", f"{dsku.get('name')} is billed per hour whether used or not.")
            else:
                plan.add(WARN, "Deployment type", f"{dsku.get('name')}: requests may be processed outside {EXPECTED_LOCATION}.")

    # ---- Container registry
    acr_ref = _pick("Container registry", of_type("Microsoft.ContainerRegistry/registries"), registry, plan)
    acr = None
    if acr_ref:
        acr = az(["acr", "show", "--resource-group", rg, "--name", acr_ref["name"]])
        plan.registry, plan.login_server = acr["name"], acr["loginServer"]
        plan.add(INFO, "Container registry", f"{acr['name']} ({acr['sku']['name']}), {acr['loginServer']}.")
        plan.add(PASS if not acr.get("adminUserEnabled") else WARN, "Registry admin user",
                 "disabled; images are pulled with managed identity." if not acr.get("adminUserEnabled")
                 else "enabled; not needed when pulling with managed identity.")

    # ---- Container app
    app_ref = _pick("Container app", of_type("Microsoft.App/containerApps"), app, plan)
    if not app_ref:
        return _finish_quota(plan, tokens_per_label)
    capp = az(["containerapp", "show", "--resource-group", rg, "--name", app_ref["name"]])
    plan.app = capp["name"]
    cprops = capp.get("properties", {})
    conf, template = cprops.get("configuration", {}) or {}, cprops.get("template", {}) or {}

    ingress = conf.get("ingress") or {}
    plan.fqdn, plan.target_port = ingress.get("fqdn"), ingress.get("targetPort")
    if ingress.get("external"):
        plan.add(PASS, "Ingress", f"external at https://{plan.fqdn}, target port {plan.target_port} "
                                  "(the app is told to listen on it; ingress is not changed).")
    else:
        plan.add(FAIL, "Ingress", "not external: reviewers need a public URL with no login.")
    if ingress.get("allowInsecure"):
        plan.add(WARN, "Ingress", "allowInsecure is on; HTTPS-only is expected.")

    containers = template.get("containers") or [{}]
    res = containers[0].get("resources") or {}
    plan.cpu = float(res.get("cpu") or 0)
    mem = float(str(res.get("memory") or "0Gi").rstrip("Gi") or 0)
    sized = plan.cpu >= 1 and mem >= 2
    plan.add(PASS if sized else WARN, "Container size",
             f"{plan.cpu:g} vCPU / {mem:g} GiB" + ("" if sized else
             " (planned 1 vCPU / 2 GiB: each label also runs offline OCR, which is CPU-bound)."))
    scale = template.get("scale") or {}
    plan.max_replicas = int(scale.get("maxReplicas") or 10)
    min_r = int(scale.get("minReplicas") or 0)
    plan.add(INFO, "Replicas", f"{min_r}-{plan.max_replicas}" + (
        ". With 0 the first request after an idle period waits for a cold start (often 10-30 s)."
        if min_r == 0 else "."))

    # ---- identity, registry pull and model access
    identity = capp.get("identity") or {}
    principals = {}  # identity reference as Container Apps names it -> (principalId, clientId)
    if "SystemAssigned" in (identity.get("type") or ""):
        principals["system"] = (identity.get("principalId"), None)
    for rid, uai in (identity.get("userAssignedIdentities") or {}).items():
        principals[rid.lower()] = (uai.get("principalId"), uai.get("clientId"))
    if not principals:
        plan.add(FAIL, "Managed identity", "the app has no managed identity.")
        return _finish_quota(plan, tokens_per_label)

    if "system" in principals:
        model_principal = principals["system"][0]
        plan.add(PASS, "Managed identity", "system-assigned; the app signs in to Azure OpenAI with it.")
    elif len(principals) == 1:
        model_principal, plan.identity_client_id = next(iter(principals.values()))
        plan.add(PASS, "Managed identity", "user-assigned; deploy sets AZURE_CLIENT_ID so the app signs in with it.")
    else:
        plan.add(FAIL, "Managed identity", "several user-assigned identities and no system identity: "
                                           "cannot tell which one the app should use.")
        model_principal = None

    if aoai and model_principal:
        _role_finding(plan, "Model access role", _roles_for(az, aoai["id"], model_principal),
                      OPENAI_ROLES_LEAST, OPENAI_ROLES_BROADER, "Cognitive Services OpenAI User on the Azure OpenAI resource")

    if acr:
        reg = next((r for r in conf.get("registries") or [] if r.get("server", "").lower() == acr["loginServer"].lower()), None)
        if not reg:
            plan.add(FAIL, "Registry pull", f"the app has no registry entry for {acr['loginServer']}.")
        elif reg.get("passwordSecretRef"):
            plan.add(WARN, "Registry pull", "uses a registry password; managed identity is expected.")
        else:
            ref = (reg.get("identity") or "").lower()
            pull_principal = (principals.get(ref) or (None, None))[0]
            if not pull_principal:
                plan.add(FAIL, "Registry pull", f"registry identity \"{reg.get('identity')}\" is not assigned to the app.")
            else:
                _role_finding(plan, "Registry pull role", _roles_for(az, acr["id"], pull_principal),
                              ACR_ROLES_LEAST, ACR_ROLES_BROADER, "AcrPull on the registry")

    return _finish_quota(plan, tokens_per_label)


def _finish_quota(plan: Plan, tokens_per_label: int) -> Plan:
    if plan.capacity_k:
        total = pace_per_replica(plan.capacity_k, 1, tokens_per_label)
        paced = (f"the app paces {pace_per_replica(plan.capacity_k, plan.max_replicas, tokens_per_label)}/min "
                 f"per replica x {plan.max_replicas}" if plan.max_replicas else "per-replica pace set once the app exists")
        level = WARN if total < 30 else INFO
        plan.add(level, "Model quota",
                 f"{plan.capacity_k}K tokens/min ({plan.capacity_k} requests/min) is about {total} labels/min in "
                 f"total at ~{tokens_per_label} counted tokens per label; {paced}. Labels over the pace use "
                 "offline OCR (safe: never a false Pass; bold shows Needs review)." + (" A 300-label batch would mostly run offline; raising the deployment's "
                 "TPM has no fixed cost on Standard." if level == WARN else ""))
    return plan


def app_settings(plan: Plan, tokens_per_label: int) -> dict[str, str]:
    env = dict(APP_SETTINGS)
    env["AZURE_OPENAI_ENDPOINT"] = plan.endpoint or ""
    env["AZURE_OPENAI_DEPLOYMENT"] = plan.model_deployment or ""
    env["PORT"] = str(plan.target_port or 8000)
    env["MAX_CONCURRENT_VERIFICATIONS"] = "3" if (plan.cpu or 0) >= 1 else "2"
    if plan.capacity_k:
        env["CLOUD_REQUESTS_PER_MINUTE"] = str(pace_per_replica(plan.capacity_k, plan.max_replicas or 1, tokens_per_label))
    if plan.identity_client_id:
        env["AZURE_CLIENT_ID"] = plan.identity_client_id
    return env


def print_plan(plan: Plan) -> None:
    width = max(len(f.item) for f in plan.findings) if plan.findings else 10
    for f in plan.findings:
        print(f"[{f.level}] {f.item.ljust(width)}  {f.detail}")
    fails = sum(f.level == FAIL for f in plan.findings)
    warns = sum(f.level == WARN for f in plan.findings)
    print(f"\n{'Ready to deploy' if plan.ok else 'Not ready'}: {fails} blocking, {warns} warnings.")


def git_tag(allow_dirty: bool) -> str:
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    if dirty and not allow_dirty:
        raise SystemExit("The working tree has uncommitted changes; commit first so the image tag names the "
                         "exact source (or pass --allow-dirty for a test build).")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return sha + ("-dirty" if dirty else "")


def http_json(url: str, timeout: float = 10) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def smoke(fqdn: str, wait_s: float = 300, get: Callable = http_json, sleep: Callable = time.sleep) -> list[str]:
    """Health and config only: no label is verified, so no model call is made."""
    base = f"https://{fqdn}"
    deadline = time.monotonic() + wait_s
    while True:
        try:
            if get(f"{base}/api/health").get("status") == "ok":
                break
        except Exception:
            pass
        if time.monotonic() > deadline:
            return [f"{base}/api/health did not answer ok within {wait_s:g} s."]
        sleep(5)
    cfg = get(f"{base}/api/config")
    problems = []
    if not cfg.get("providers", {}).get("local"):
        problems.append("offline OCR is not available in the container (Tesseract missing?).")
    if not cfg.get("providers", {}).get("azure"):
        problems.append("the cloud engine is not configured (AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_DEPLOYMENT).")
    if cfg.get("default_provider") != "auto":
        problems.append(f"default engine is {cfg.get('default_provider')}, expected auto.")
    return problems


def deploy(az_cmd: Callable, plan: Plan, rg: str, tag: str, tokens_per_label: int, skip_build: bool) -> None:
    image = f"{plan.login_server}/{IMAGE_REPO}:{tag}"
    if not skip_build:
        print(f"== Building {image} in the registry (az acr build)")
        subprocess.run(["az", "acr", "build", "--registry", plan.registry, "--image", f"{IMAGE_REPO}:{tag}", str(REPO)],
                       check=True)
    env = app_settings(plan, tokens_per_label)
    print(f"== Updating container app {plan.app} to {image}")
    for k, v in sorted(env.items()):
        print(f"   {k}={v}")
    az_cmd(["containerapp", "update", "--resource-group", rg, "--name", plan.app, "--image", image,
            "--set-env-vars", *[f"{k}={v}" for k, v in sorted(env.items())]])
    print(f"== Smoke test (health and config only; no model calls) https://{plan.fqdn}")
    problems = smoke(plan.fqdn)
    for p in problems:
        print(f"[FAIL] {p}")
    if problems:
        raise SystemExit(1)
    print(f"Deployed: https://{plan.fqdn}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["check", "deploy"])
    ap.add_argument("--resource-group", "-g", default="rg-ttb-label-verifier")
    ap.add_argument("--app")
    ap.add_argument("--registry")
    ap.add_argument("--openai", dest="openai_name")
    ap.add_argument("--model-deployment")
    ap.add_argument("--tokens-per-label", type=int, default=DEFAULT_TOKENS_PER_LABEL,
                    help="tokens Azure counts per label call, used to pace cloud calls (default %(default)s)")
    ap.add_argument("--tag", help="image tag (default: current git commit)")
    ap.add_argument("--allow-dirty", action="store_true")
    ap.add_argument("--skip-build", action="store_true", help="deploy an image tag that is already in the registry")
    ap.add_argument("--confirm", action="store_true", help="required for deploy")
    a = ap.parse_args(argv)

    plan = check(run_az, a.resource_group, a.app, a.registry, a.openai_name, a.model_deployment, a.tokens_per_label)
    print_plan(plan)
    if a.command == "check":
        return 0 if plan.ok else 1
    if not plan.ok:
        print("Fix the blocking items first (they belong to the infrastructure setup).", file=sys.stderr)
        return 1
    if not a.confirm:
        print("\nDry run. Settings that deploy would apply:")
        for k, v in sorted(app_settings(plan, a.tokens_per_label).items()):
            print(f"   {k}={v}")
        print("Re-run with --confirm to build the image and update the app.")
        return 0
    deploy(run_az, plan, a.resource_group, a.tag or git_tag(a.allow_dirty), a.tokens_per_label, a.skip_build)
    return 0


if __name__ == "__main__":
    sys.exit(main())
