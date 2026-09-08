import json
from pathlib import Path

import pytest
from scripts.run_batch import (
    BatchConfig, CoordinatorError, _scraper_summary, build_parser, run_cohort,
)
IDS = ("00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002")
class FakeKubectl:
    def __init__(self, observed=IDS, extractor_exit=0, stage_exits=None):
        self.calls, self.created, self.created_by_name = [], [], {}
        self.observed, self.extractor_exit = observed, extractor_exit
        self.stage_exits = stage_exits or {}
        self.cron = {"kind": "CronJob", "metadata": {"name": "scraper"}, "spec": {
            "suspend": True, "jobTemplate": {"spec": {"template": {"spec": {
                "containers": [{"name": "scraper", "image": "job-radar:dev"}]
            }}}}
        }}

    def __call__(self, command, *, input_text=None, timeout):
        self.calls.append((command, input_text, timeout))
        args = command[1:]
        if args[:2] == ["get", "cronjob/scraper"]:
            return json.dumps(self.cron)
        if args[:1] == ["create"] and "--dry-run=client" in args:
            stage = "extractor" if "extractor-job.yaml" in " ".join(args) else "classifier"
            return json.dumps({"kind": "Job", "spec": {"template": {"spec": {
                "containers": [{"name": stage, "image": f"job-radar-{stage}:dev"}]
            }}}})
        if args[:1] == ["create"]:
            job = json.loads(input_text)
            self.created.append(job)
            self.created_by_name[job["metadata"]["name"]] = job
            stage = job["metadata"]["labels"]["job-radar-coach/stage"]
            return json.dumps({"metadata": {"uid": f"uid-{job['metadata']['name']}"}})
        if args[:1] == ["get"] and args[1].startswith("job/"):
            name = args[1].split("/", 1)[1]
            job = self.created_by_name[name]
            stage = job["metadata"]["labels"]["job-radar-coach/stage"]
            chunk = job["metadata"]["labels"].get("job-radar-coach/chunk")
            code = self.stage_exits.get((stage, int(chunk) if chunk is not None else None),
                                        self.extractor_exit if stage == "extractor" else 0)
            failed = bool(code)
            return json.dumps({"status": {"failed" if failed else "succeeded": 1}})
        if args[:2] == ["get", "pods"]:
            name = args[args.index("-l") + 1].split("=", 1)[1]
            job = self.created_by_name[name]
            stage = job["metadata"]["labels"]["job-radar-coach/stage"]
            chunk = job["metadata"]["labels"].get("job-radar-coach/chunk")
            code = self.stage_exits.get((stage, int(chunk) if chunk is not None else None),
                                        self.extractor_exit if stage == "extractor" else 0)
            pod = {"metadata": {"name": f"{name}-pod"}, "status": {"containerStatuses": [{
                "name": stage, "imageID": f"sha256:{stage}",
                "state": {"terminated": {"exitCode": code}},
            }]}}
            return json.dumps({"items": [pod]})
        stage = args[args.index("-c") + 1]
        if stage == "scraper":
            return json.dumps({
                "fetched_count": max(7, len(self.observed)),
                "matched_count": max(4, len(self.observed)),
                "new_count": int(bool(self.observed)),
                "observed_posting_ids": list(self.observed),
                "inserted_posting_ids": list(self.observed[:1]),
            }) + "\n"
        pod_name = args[1].split("/", 1)[1]
        job = self.created_by_name[pod_name.removesuffix("-pod")]
        chunk = job["metadata"]["labels"].get("job-radar-coach/chunk")
        failed = int(bool(self.stage_exits.get(
            (stage, int(chunk) if chunk is not None else None),
            self.extractor_exit if stage == "extractor" else 0,
        )))
        model_args = job["spec"]["template"]["spec"]["containers"][0]["args"]
        selected = sum(value == "--posting-id" for value in model_args)
        outcome = "extracted" if stage == "extractor" else "scored"
        return json.dumps({"selected": selected, outcome: selected - failed,
                           "failed": failed}) + "\n"

@pytest.mark.parametrize("checkout_dir", ["repo", "classifier-copy"])
def test_correlates_all_ids_and_continues_after_extractor_failure(monkeypatch, checkout_dir):
    monkeypatch.setattr("scripts.run_batch.REPO_ROOT", Path("/tmp") / checkout_dir)
    fake, config = FakeKubectl(extractor_exit=1), BatchConfig(limit=2, classifier_provider="codex")
    receipt = run_cohort(config, kubectl=fake, run_id="funnel-20260908t120000z-1234abcd")
    assert [receipt[key] for key in ("cohort_count", "fetched", "matched", "new", "extracted", "scored")] == [2, 7, 4, 1, 1, 2]
    assert receipt["selected_counts"] == {"extractor": 2, "classifier": 2}
    assert receipt["failures"] == [{"stage": "extractor", "failure": "JobFailed"}]
    assert fake.cron["kind"] == "CronJob" and len(fake.created) == 3
    assert receipt["jobs"]["extractor"]["job_uid"].startswith("uid-extractor-")
    assert (receipt["jobs"]["extractor"]["exit_code"], receipt["jobs"]["extractor"]["image_id"]) == (1, "sha256:extractor")
    assert len({job["metadata"]["name"] for job in fake.created}) == 3
    for job in fake.created:
        assert (job["metadata"]["namespace"], job["spec"]["activeDeadlineSeconds"],
                job["spec"]["backoffLimit"], job["spec"]["template"]["spec"]["restartPolicy"]) == ("job-radar-coach", 900, 0, "Never")
    for job in fake.created[1:]:
        args = job["spec"]["template"]["spec"]["containers"][0]["args"]
        assert [args[index + 1] for index, value in enumerate(args) if value == "--posting-id"] == list(IDS)
    assert "BRAIN" not in {item["name"] for item in fake.created[1]["spec"]["template"]["spec"]["containers"][0].get("env", [])}
    assert {item["name"]: item.get("value") for item in fake.created[2]["spec"]["template"]["spec"]["containers"][0]["env"]}["BRAIN"] == "codex"
    assert not any(call[0][1] in {"patch", "delete", "replace"} for call in fake.calls)
    _assert_lifecycle(fake.calls)

def _assert_lifecycle(calls):
    lifecycle = []
    for command, body, _timeout in calls:
        if body:
            stage = json.loads(body)["metadata"]["labels"]["job-radar-coach/stage"]
        else:
            stages = [name for name in ("scraper", "extractor", "classifier")
                      if any(name in Path(argument).name for argument in command)]
            assert len(stages) == 1
            stage = stages[0]
        action = "dry-run" if "--dry-run=client" in command else command[1]
        lifecycle.append((stage, action))
    assert lifecycle == [("scraper", action) for action in ("get", "create", "get", "get", "logs")] + [
        (stage, action) for stage in ("extractor", "classifier")
        for action in ("dry-run", "create", "get", "get", "logs")
    ]

def test_empty_cohort_skips_model_jobs():
    fake = FakeKubectl(observed=())
    receipt = run_cohort(BatchConfig(), kubectl=fake, run_id="funnel-empty-1234abcd")
    assert len(fake.created) == 1 and receipt["extracted"] == receipt["scored"] == 0
    assert receipt["jobs"]["extractor"] == receipt["jobs"]["classifier"] == {"skipped": "empty_cohort"}

@pytest.mark.parametrize("ids", [["not-a-uuid"], [IDS[0], IDS[0]]])
def test_invalid_scraper_cohort_never_starts_models(ids):
    fake = FakeKubectl(observed=ids)
    receipt = run_cohort(BatchConfig(), kubectl=fake, run_id="funnel-invalid-1234abcd")
    assert len(fake.created) == 1 and receipt["cohort_count"] is None
    assert receipt["failures"] == [{"stage": "scraper", "failure": "InvalidReceipt"}]

def test_rejects_malformed_or_ambiguous_summary_lines():
    with pytest.raises(CoordinatorError):
        _scraper_summary("not-json\n")
    valid = FakeKubectl()(["kubectl", "logs", "pod/x", "-c", "scraper"], timeout=1)
    with pytest.raises(CoordinatorError):
        _scraper_summary(valid + valid)


def test_retains_created_job_identity_when_logs_fail():
    fake = FakeKubectl()
    def runner(command, **kwargs):
        if command[1] == "logs" and "extractor" in command:
            raise CoordinatorError("KubectlTimeout")
        return fake(command, **kwargs)
    receipt = run_cohort(BatchConfig(), kubectl=runner, run_id="funnel-partial-receipt")
    assert receipt["jobs"]["extractor"]["job_uid"].startswith("uid-extractor-")
    assert receipt["jobs"]["extractor"]["exit_code"] == 0
    assert receipt["extracted"] is None
    assert receipt["scored"] == 2


def test_rejects_inconsistent_insertion_count():
    value = json.loads(FakeKubectl()(["kubectl", "logs", "pod/x", "-c", "scraper"], timeout=1))
    value["new_count"] = 2
    with pytest.raises(CoordinatorError):
        _scraper_summary(json.dumps(value))


def test_all_observed_chunks_every_id_once_and_aggregates_failures():
    observed = tuple(
        f"00000000-0000-0000-0000-{index:012d}" for index in range(1, 8)
    )
    fake = FakeKubectl(observed=observed, stage_exits={("extractor", 1): 1})
    receipt = run_cohort(
        BatchConfig(limit=3, all_observed=True), kubectl=fake,
        run_id="funnel-all-observed-1234abcd",
    )

    assert receipt["mode"] == "all_observed" and receipt["chunk_count"] == 3
    assert receipt["selected_counts"] == {"extractor": 7, "classifier": 7}
    assert (receipt["extracted"], receipt["scored"]) == (6, 7)
    assert receipt["aggregate_receipts"] == {
        "extractor": {"selected": 7, "completed": 6, "failed": 1,
                      "reported_chunks": 3, "chunk_count": 3, "complete": True},
        "classifier": {"selected": 7, "completed": 7, "failed": 0,
                       "reported_chunks": 3, "chunk_count": 3, "complete": True},
    }
    assert receipt["failures"] == [
        {"stage": "extractor", "failure": "JobFailed", "chunk": 1}
    ]
    assert len(receipt["jobs"]["extractor"]) == len(receipt["jobs"]["classifier"]) == 3
    model_jobs = fake.created[1:]
    assert len({job["metadata"]["name"] for job in model_jobs}) == 6
    for stage in ("extractor", "classifier"):
        stage_ids = [
            args[index + 1]
            for job in sorted(
                (item for item in model_jobs
                 if item["metadata"]["labels"]["job-radar-coach/stage"] == stage),
                key=lambda item: item["metadata"]["labels"]["job-radar-coach/chunk"],
            )
            for args in [job["spec"]["template"]["spec"]["containers"][0]["args"]]
            for index, value in enumerate(args) if value == "--posting-id"
        ]
        assert stage_ids == list(observed)


def test_all_observed_cli_is_explicit_and_keeps_default_off():
    assert BatchConfig(**vars(build_parser().parse_args([]))).all_observed is False
    configured = BatchConfig(**vars(build_parser().parse_args(["--all-observed", "--limit", "3"])))
    assert configured.all_observed is True and configured.limit == 3
