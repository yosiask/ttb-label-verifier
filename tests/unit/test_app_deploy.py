"""Application-only deployment tool against a fake Azure CLI: no Azure calls, no cost."""

import copy
import json
import importlib.util
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "app_deploy", Path(__file__).resolve().parents[2] / "deploy" / "azure" / "app_deploy.py")
ad = importlib.util.module_from_spec(spec)
sys.modules["app_deploy"] = ad
spec.loader.exec_module(ad)

RG = "rg-ttb-label-verifier"
SUB = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/" + RG
AOAI_ID = SUB + "/providers/Microsoft.CognitiveServices/accounts/aoai-ttb"
ACR_ID = SUB + "/providers/Microsoft.ContainerRegistry/registries/acrttb"
UAMI_ID = SUB + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-ttb"

# Shaped like `az ... -o json` output for the planned setup: dedicated S0 resource,
# gpt-4.1-mini Standard 30K TPM, Basic registry, Consumption app with 0-2 replicas.
WORLD = {
    ("account", "show"): {"name": "Microsoft Azure Sponsorship", "user": {"name": "ops@example.com"}},
    ("group", "show"): {"location": "eastus2", "id": SUB},
    ("resource", "list"): [
        {"type": "Microsoft.CognitiveServices/accounts", "name": "aoai-ttb"},
        {"type": "Microsoft.ContainerRegistry/registries", "name": "acrttb"},
        {"type": "Microsoft.App/managedEnvironments", "name": "cae-ttb"},
        {"type": "Microsoft.App/containerApps", "name": "ttb-label-verifier"},
    ],
    ("cognitiveservices", "account", "show"): {
        "id": AOAI_ID, "kind": "OpenAI", "sku": {"name": "S0"},
        "properties": {"endpoint": "https://aoai-ttb.openai.azure.com/", "customSubDomainName": "aoai-ttb",
                       "disableLocalAuth": True, "publicNetworkAccess": "Enabled"}},
    ("cognitiveservices", "account", "deployment", "list"): [
        {"name": "gpt-41-mini", "sku": {"name": "Standard", "capacity": 30},
         "properties": {"model": {"format": "OpenAI", "name": "gpt-4.1-mini", "version": "2025-04-14"}}}],
    ("acr", "show"): {"id": ACR_ID, "name": "acrttb", "loginServer": "acrttb.azurecr.io",
                      "sku": {"name": "Basic"}, "adminUserEnabled": False},
    ("containerapp", "show"): {
        "name": "ttb-label-verifier",
        "identity": {"type": "SystemAssigned", "principalId": "p-system"},
        "properties": {
            "configuration": {
                "ingress": {"external": True, "targetPort": 80, "fqdn": "ttb.example.azurecontainerapps.io",
                            "allowInsecure": False},
                "registries": [{"server": "acrttb.azurecr.io", "identity": "system"}]},
            "template": {"containers": [{"name": "app", "resources": {"cpu": 1.0, "memory": "2Gi"}}],
                         "scale": {"minReplicas": 0, "maxReplicas": 2}}}},
    ("role", "assignment", "list", AOAI_ID): [
        {"principalId": "p-system", "roleDefinitionName": "Cognitive Services OpenAI User"},
        {"principalId": "someone-else", "roleDefinitionName": "Owner"}],
    ("role", "assignment", "list", ACR_ID): [{"principalId": "p-system", "roleDefinitionName": "AcrPull"}],
}


class FakeAz:
    def __init__(self, world=None):
        self.world = copy.deepcopy(world or WORLD)
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if "--scope" in args:
            return self.world[tuple(args[:3]) + (args[args.index("--scope") + 1],)]
        for n in (5, 4, 3, 2):
            if tuple(args[:n]) in self.world:
                return self.world[tuple(args[:n])]
        raise AssertionError(f"unexpected az call {args}")


def levels(plan):
    return {f.item: f.level for f in plan.findings}


def test_planned_setup_is_ready_and_read_only():
    az = FakeAz()
    plan = ad.check(az, RG)
    assert plan.ok, [f for f in plan.findings if f.level == "FAIL"]
    lv = levels(plan)
    for item in ("Resource group", "Azure OpenAI resource", "Azure OpenAI auth", "Model", "Deployment type",
                 "Ingress", "Container size", "Managed identity", "Model access role", "Registry pull role"):
        assert lv[item] == "PASS", item
    assert all("show" in c or "list" in c for c in az.calls)
    assert not any(w in " ".join(c) for c in az.calls for w in ("create", "update", "build", "set", "delete"))


def test_low_quota_flagged():
    w = copy.deepcopy(WORLD)
    w[("cognitiveservices", "account", "deployment", "list")][0]["sku"]["capacity"] = 10
    assert levels(ad.check(FakeAz(w), RG))["Model quota"] == "WARN"


def test_30k_tpm_cloud_paced_inside_quota():
    plan = ad.check(FakeAz(), RG)
    env = ad.app_settings(plan, ad.DEFAULT_TOKENS_PER_LABEL)
    # 30K TPM x 0.8 / 1300 tokens = 18.5 labels/min in total -> 9 per replica x 2 replicas.
    assert env["CLOUD_REQUESTS_PER_MINUTE"] == "9"
    assert int(env["CLOUD_REQUESTS_PER_MINUTE"]) * plan.max_replicas * 1300 <= 30_000


def test_settings_follow_existing_infrastructure():
    plan = ad.check(FakeAz(), RG)
    env = ad.app_settings(plan, 4500)
    assert env["AZURE_OPENAI_ENDPOINT"] == "https://aoai-ttb.openai.azure.com/"
    assert env["AZURE_OPENAI_DEPLOYMENT"] == "gpt-41-mini"
    assert env["PORT"] == "80"  # match the existing ingress instead of changing it
    assert env["EXTRACTOR"] == "auto" and env["TRUSTED_PROXY_HOPS"] == "1"
    assert "AZURE_CLIENT_ID" not in env and "AZURE_OPENAI_API_KEY" not in env


@pytest.mark.parametrize("capacity,replicas,expected", [(30, 2, 2), (150, 2, 13), (30, 1, 5), (1, 3, 1)])
def test_pace_per_replica(capacity, replicas, expected):
    assert ad.pace_per_replica(capacity, replicas, 4500) == expected


def test_user_assigned_identity_sets_client_id():
    w = copy.deepcopy(WORLD)
    w[("containerapp", "show")]["identity"] = {
        "type": "UserAssigned", "userAssignedIdentities": {UAMI_ID: {"principalId": "p-uami", "clientId": "c-uami"}}}
    w[("containerapp", "show")]["properties"]["configuration"]["registries"][0]["identity"] = UAMI_ID
    w[("role", "assignment", "list", AOAI_ID)] = [{"principalId": "p-uami", "roleDefinitionName": "Cognitive Services OpenAI User"}]
    w[("role", "assignment", "list", ACR_ID)] = [{"principalId": "p-uami", "roleDefinitionName": "AcrPull"}]
    plan = ad.check(FakeAz(w), RG)
    assert plan.ok
    assert ad.app_settings(plan, 4500)["AZURE_CLIENT_ID"] == "c-uami"


@pytest.mark.parametrize("mutate,item,level", [
    (lambda w: w.__setitem__(("role", "assignment", "list", AOAI_ID), []), "Model access role", "FAIL"),
    (lambda w: w.__setitem__(("role", "assignment", "list", AOAI_ID),
                             [{"principalId": "p-system", "roleDefinitionName": "Owner"}]), "Model access role", "FAIL"),
    (lambda w: w.__setitem__(("role", "assignment", "list", AOAI_ID),
                             [{"principalId": "p-system", "roleDefinitionName": "Cognitive Services OpenAI Contributor"}]),
     "Model access role", "WARN"),
    (lambda w: w.__setitem__(("role", "assignment", "list", ACR_ID), []), "Registry pull role", "FAIL"),
    (lambda w: w[("containerapp", "show")]["properties"]["configuration"].__setitem__("registries", []),
     "Registry pull", "FAIL"),
    (lambda w: w[("containerapp", "show")].__setitem__("identity", {"type": "None"}), "Managed identity", "FAIL"),
    (lambda w: w[("containerapp", "show")]["properties"]["configuration"]["ingress"].__setitem__("external", False),
     "Ingress", "FAIL"),
    (lambda w: w[("cognitiveservices", "account", "show")]["properties"].__setitem__("customSubDomainName", None),
     "Azure OpenAI auth", "FAIL"),
    (lambda w: w[("cognitiveservices", "account", "show")]["properties"].__setitem__("disableLocalAuth", False),
     "Azure OpenAI auth", "WARN"),
    (lambda w: w[("cognitiveservices", "account", "show")]["properties"].__setitem__("publicNetworkAccess", "Disabled"),
     "Azure OpenAI network", "FAIL"),
    (lambda w: w[("cognitiveservices", "account", "deployment", "list")][0]["sku"].__setitem__("name", "ProvisionedManaged"),
     "Deployment type", "FAIL"),
    (lambda w: w[("cognitiveservices", "account", "deployment", "list")][0]["sku"].__setitem__("name", "GlobalStandard"),
     "Deployment type", "WARN"),
    (lambda w: w[("cognitiveservices", "account", "deployment", "list")][0]["properties"]["model"].__setitem__("name", "gpt-4o"),
     "Model", "WARN"),
    (lambda w: w[("containerapp", "show")]["properties"]["template"]["containers"][0]["resources"].update(cpu=0.5, memory="1Gi"),
     "Container size", "WARN"),
    (lambda w: w[("acr", "show")].__setitem__("adminUserEnabled", True), "Registry admin user", "WARN"),
])
def test_misconfigurations_are_reported(mutate, item, level):
    w = copy.deepcopy(WORLD)
    mutate(w)
    plan = ad.check(FakeAz(w), RG)
    assert levels(plan)[item] == level
    assert plan.ok is (not any(f.level == "FAIL" for f in plan.findings))


def test_missing_group_stops_early():
    w = copy.deepcopy(WORLD)
    w[("group", "show")] = None
    plan = ad.check(FakeAz(w), RG)
    assert not plan.ok and levels(plan)["Resource group"] == "FAIL"


def test_ambiguous_resources_need_a_name():
    w = copy.deepcopy(WORLD)
    w[("resource", "list")].append({"type": "Microsoft.App/containerApps", "name": "other-app"})
    plan = ad.check(FakeAz(w), RG)
    assert levels(plan)["Container app"] == "FAIL"
    assert ad.check(FakeAz(w), RG, app="ttb-label-verifier").ok


def test_smoke_never_verifies_a_label():
    seen = []

    def get(url):
        seen.append(url)
        if url.endswith("/api/health"):
            return {"status": "ok"}
        return {"providers": {"local": True, "azure": True}, "default_provider": "auto"}

    assert ad.smoke("ttb.example.io", get=get, sleep=lambda s: None) == []
    assert seen == ["https://ttb.example.io/api/health", "https://ttb.example.io/api/config"]


def test_smoke_reports_missing_cloud_config():
    def get(url):
        return {"status": "ok"} if url.endswith("health") else {"providers": {"local": True, "azure": False},
                                                                 "default_provider": "auto"}
    problems = ad.smoke("x.io", get=get, sleep=lambda s: None)
    assert len(problems) == 1 and "not configured" in problems[0]


def test_deploy_without_confirm_changes_nothing(monkeypatch, capsys):
    az = FakeAz()
    monkeypatch.setattr(ad, "run_az", az)
    monkeypatch.setattr(ad.subprocess, "run", lambda *a, **k: pytest.fail("no subprocess without --confirm"))
    assert ad.main(["deploy", "-g", RG]) == 0
    out = capsys.readouterr().out
    assert "Dry run" in out and "CLOUD_REQUESTS_PER_MINUTE=9" in out
    assert not any("update" in c for c in az.calls)


def test_deploy_clears_placeholder_start_command(monkeypatch):
    """A placeholder image's command (e.g. /http-echo) must not survive the image swap."""
    w = copy.deepcopy(WORLD)
    w[("containerapp", "show")]["properties"]["template"]["containers"][0].update(
        command=["/http-echo"], args=["-listen=:8000"])
    w[("containerapp", "update")] = {}
    az = FakeAz(w)
    plan = ad.check(az, RG)
    assert levels(plan)["Start command"] == "INFO" and plan.ok
    monkeypatch.setattr(ad, "smoke", lambda fqdn: [])
    az.world[("containerapp", "show")]["properties"]["template"]["containers"][0]["env"] = [
        {"name": "KEEP_ME", "value": "1"}, {"name": "EXTRACTOR", "value": "local"}]
    sent = {}

    def capture(args):
        if args[:2] == ["containerapp", "update"]:
            sent.update(json.load(open(args[args.index("--yaml") + 1])))
        return az(args)

    ad.deploy(capture, plan, RG, "abc123", 4500, skip_build=True)
    c = sent["properties"]["template"]["containers"][0]
    assert "command" not in c and "args" not in c
    assert c["image"] == "acrttb.azurecr.io/ttb-label-verifier:abc123"
    env = {e["name"]: e["value"] for e in c["env"]}
    assert env["KEEP_ME"] == "1" and env["EXTRACTOR"] == "auto" and env["AZURE_OPENAI_DEPLOYMENT"] == "gpt-41-mini"
    assert c["resources"] == {"cpu": 1.0, "memory": "2Gi"}
    assert sent["properties"]["template"]["scale"] == {"minReplicas": 0, "maxReplicas": 2}


def test_150k_tpm_is_not_flagged():
    w = copy.deepcopy(WORLD)
    w[("cognitiveservices", "account", "deployment", "list")][0]["sku"]["capacity"] = 150
    plan = ad.check(FakeAz(w), RG)
    assert levels(plan)["Model quota"] == "INFO"
    assert ad.app_settings(plan, 4500)["CLOUD_REQUESTS_PER_MINUTE"] == "13"
