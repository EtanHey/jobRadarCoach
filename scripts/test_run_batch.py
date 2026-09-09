import json
from pathlib import Path

import pytest
from scripts.run_batch import (
    BatchConfig, CoordinatorError, _model_summary, _scraper_summary, build_parser,
    run_cohort,
)
IDS = ("00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002")
class FakeKubectl:
    def __init__(self, observed=IDS, extractor_exit=0, stage_exits=None, stage_selected=None):
        self.calls, self.created, self.created_by_name = [], [], {}
        self.observed, self.extractor_exit = observed, extractor_exit
        self.stage_exits = stage_exits or {}
        self.stage_selected = stage_selected or {}
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
            return json.dumps({
                "metadata": {"uid": f"uid-{name}"},
                "status": {"failed" if failed else "succeeded": 1},
            })
        if args[:2] == ["get", "pods"]:
            name = args[args.index("-l") + 1].split("=", 1)[1]
            job = self.created_by_name[name]
            stage = job["metadata"]["labels"]["job-radar-coach/stage"]
            chunk = job["metadata"]["labels"].get("job-radar-coach/chunk")
            code = self.stage_exits.get((stage, int(chunk) if chunk is not None else None),
                                        self.extractor_exit if stage == "extractor" else 0)
            pod = {"metadata": {
                "name": f"{name}-pod", "uid": f"uid-{name}-pod",
                "ownerReferences": [{
                    "apiVersion": "batch/v1", "kind": "Job", "name": name,
                    "uid": f"uid-{name}", "controller": True,
                }],
            }, "status": {"containerStatuses": [{
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
        requested = [model_args[index + 1] for index, value in enumerate(model_args)
                     if value == "--posting-id"]
        limit = int(model_args[model_args.index("--limit") + 1])
        selected_ids = list(self.stage_selected.get(
            (stage, int(chunk) if chunk is not None else None), requested[:limit],
        ))
        selected = len(selected_ids)
        outcome = "extracted" if stage == "extractor" else "scored"
        summary = {"selected": selected, outcome: selected - failed, "failed": failed}
        if len(set(requested)) <= limit:
            skipped_ids = [item for item in dict.fromkeys(requested)
                           if item not in selected_ids]
            summary.update(
                skipped=len(skipped_ids),
                selected_posting_ids=selected_ids,
                skipped_posting_ids=skipped_ids,
            )
        return json.dumps(summary) + "\n"

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
                job["spec"]["backoffLimit"], job["spec"]["ttlSecondsAfterFinished"],
                job["spec"]["template"]["spec"]["restartPolicy"]) == (
                    "job-radar-coach", 900, 0, 3600, "Never",
                )
    for job in fake.created[1:]:
        args = job["spec"]["template"]["spec"]["containers"][0]["args"]
        assert [args[index + 1] for index, value in enumerate(args) if value == "--posting-id"] == list(IDS)
    assert "BRAIN" not in {item["name"] for item in fake.created[1]["spec"]["template"]["spec"]["containers"][0].get("env", [])}
    assert {item["name"]: item.get("value") for item in fake.created[2]["spec"]["template"]["spec"]["containers"][0]["env"]}["BRAIN"] == "codex"
    assert not any(call[0][1] in {"patch", "delete", "replace"} for call in fake.calls)
    _assert_lifecycle(fake.calls)


def test_all_tracked_job_templates_retain_receipts_for_one_hour():
    templates = [
        path for path in sorted((Path(__file__).parents[1] / "k8s").glob("*.yaml"))
        if not path.name.startswith("livekit")
    ]
    batch_templates = {
        path.name: path.read_text(encoding="utf-8")
        for path in templates
        if path.read_text(encoding="utf-8").startswith("apiVersion: batch/v1\n")
    }

    assert set(batch_templates) == {
        "classifier-job.yaml", "extractor-job.yaml", "scraper-cronjob.yaml",
    }
    for name in ("classifier-job.yaml", "extractor-job.yaml"):
        assert "\nspec:\n  ttlSecondsAfterFinished: 3600\n" in batch_templates[name]
    assert (
        "  jobTemplate: # layer 2: the Job\n"
        "    spec:\n"
        "      ttlSecondsAfterFinished: 3600\n"
    ) in batch_templates["scraper-cronjob.yaml"]

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


def test_all_observed_preserves_typed_scraper_poll_failure():
    fake = FakeKubectl()

    def runner(command, **kwargs):
        if command[1:3] == ["get", "job/scraper-funnel-poll-failure"]:
            raise CoordinatorError("KubectlTimeout")
        return fake(command, **kwargs)

    receipt = run_cohort(
        BatchConfig(all_observed=True), kubectl=runner,
        run_id="funnel-poll-failure",
    )

    assert receipt["mode"] == "all_observed" and receipt["chunk_count"] == 0
    assert receipt["cohort_count"] is None
    assert receipt["failures"] == [
        {"stage": "scraper", "failure": "KubectlTimeout"}
    ]
    assert receipt["jobs"]["scraper"]["job_uid"].startswith("uid-scraper-")
    assert receipt["jobs"]["extractor"] == {"skipped": "scraper_failure"}
    assert receipt["jobs"]["classifier"] == {"skipped": "scraper_failure"}
    assert len(fake.created) == 1

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
    assert receipt["scored"] == 1


def test_transient_read_timeout_recovers_without_recreating_job(monkeypatch):
    fake = FakeKubectl()
    failed_once = False

    def runner(command, **kwargs):
        nonlocal failed_once
        if command[1:3] == ["get", "job/extractor-funnel-read-recovery"] and not failed_once:
            failed_once = True
            raise CoordinatorError("KubectlTimeout")
        return fake(command, **kwargs)

    monkeypatch.setattr("scripts.run_batch.time.sleep", lambda _delay: None)
    receipt = run_cohort(
        BatchConfig(), kubectl=runner, run_id="funnel-read-recovery",
    )

    assert receipt["failures"] == []
    assert receipt["jobs"]["extractor"]["creation_outcome"] == "created"
    assert sum(call[0][1] == "create" and bool(call[1]) for call in fake.calls) == 3


def test_transient_log_timeout_recovers_after_owned_pod_check(monkeypatch):
    fake = FakeKubectl()
    failed_once = False

    def runner(command, **kwargs):
        nonlocal failed_once
        if command[1] == "logs" and "extractor" in command and not failed_once:
            failed_once = True
            raise CoordinatorError("KubectlTimeout")
        return fake(command, **kwargs)

    monkeypatch.setattr("scripts.run_batch.time.sleep", lambda _delay: None)
    receipt = run_cohort(BatchConfig(), kubectl=runner, run_id="funnel-log-recovery")

    assert receipt["failures"] == []
    assert receipt["jobs"]["extractor"]["pod_uid"].endswith("-pod")
    assert sum(call[0][1] == "create" and bool(call[1]) for call in fake.calls) == 3


def test_recovered_read_rejects_replaced_job_uid(monkeypatch):
    fake = FakeKubectl()
    timed_out = False

    def runner(command, **kwargs):
        nonlocal timed_out
        if command[1:3] == ["get", "job/extractor-funnel-wrong-uid"]:
            if not timed_out:
                timed_out = True
                raise CoordinatorError("KubectlTimeout")
            value = json.loads(fake(command, **kwargs))
            value["metadata"]["uid"] = "replacement-uid"
            return json.dumps(value)
        return fake(command, **kwargs)

    monkeypatch.setattr("scripts.run_batch.time.sleep", lambda _delay: None)
    receipt = run_cohort(BatchConfig(), kubectl=runner, run_id="funnel-wrong-uid")

    assert {item["failure"] for item in receipt["failures"]} == {"JobUIDMismatch"}
    assert receipt["jobs"]["extractor"]["job_uid"] == "uid-extractor-funnel-wrong-uid"
    assert sum(call[0][1] == "create" and bool(call[1]) for call in fake.calls) == 3


def test_persistent_read_timeout_is_bounded(monkeypatch):
    fake = FakeKubectl()
    read_attempts = 0

    def runner(command, **kwargs):
        nonlocal read_attempts
        if command[1:3] == ["get", "job/extractor-funnel-read-timeout"]:
            read_attempts += 1
            raise CoordinatorError("KubectlTimeout")
        return fake(command, **kwargs)

    monkeypatch.setattr("scripts.run_batch.time.sleep", lambda _delay: None)
    receipt = run_cohort(BatchConfig(), kubectl=runner, run_id="funnel-read-timeout")

    assert {item["failure"] for item in receipt["failures"]} == {"KubectlTimeout"}
    assert read_attempts == 3
    assert sum(call[0][1] == "create" and bool(call[1]) for call in fake.calls) == 3


def test_create_timeout_has_unknown_outcome_and_is_never_retried():
    fake = FakeKubectl()
    extractor_create_attempts = 0

    def runner(command, **kwargs):
        nonlocal extractor_create_attempts
        if command[1] == "create" and kwargs.get("input_text"):
            job = json.loads(kwargs["input_text"])
            if job["metadata"]["labels"]["job-radar-coach/stage"] == "extractor":
                extractor_create_attempts += 1
                raise CoordinatorError("KubectlTimeout")
        return fake(command, **kwargs)

    receipt = run_cohort(BatchConfig(), kubectl=runner, run_id="funnel-create-timeout")

    assert {item["failure"] for item in receipt["failures"]} == {
        "JobCreationOutcomeUnknown",
    }
    assert receipt["jobs"]["extractor"] == {
        "job_name": "extractor-funnel-create-timeout",
        "creation_outcome": "unknown",
    }
    assert extractor_create_attempts == 1


def test_rejects_pod_without_exact_job_owner():
    fake = FakeKubectl()

    def runner(command, **kwargs):
        value = fake(command, **kwargs)
        if command[1:3] == ["get", "pods"] and "extractor" in command[command.index("-l") + 1]:
            payload = json.loads(value)
            payload["items"][0]["metadata"]["ownerReferences"][0]["uid"] = "other-uid"
            return json.dumps(payload)
        return value

    receipt = run_cohort(BatchConfig(), kubectl=runner, run_id="funnel-wrong-pod-owner")

    assert {item["failure"] for item in receipt["failures"]} == {
        "JobPodOwnershipMismatch",
    }


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
    assert receipt["skipped_counts"] == {"extractor": 0, "classifier": 0}
    assert (receipt["extracted"], receipt["scored"]) == (6, 7)
    assert receipt["aggregate_receipts"] == {
        "extractor": {"selected": 7, "completed": 6, "failed": 1, "skipped": 0,
                      "reported_chunks": 3, "chunk_count": 3, "complete": True},
        "classifier": {"selected": 7, "completed": 7, "failed": 0, "skipped": 0,
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


def test_all_current_assignment_is_terminal_success_with_exact_skips():
    skipped = {(stage, 0): () for stage in ("extractor", "classifier")}
    receipt = run_cohort(
        BatchConfig(limit=2, all_observed=True),
        kubectl=FakeKubectl(stage_selected=skipped), run_id="funnel-all-current",
    )

    assert receipt["failures"] == []
    assert receipt["selected_counts"] == {"extractor": 0, "classifier": 0}
    assert receipt["skipped_counts"] == {"extractor": 2, "classifier": 2}
    assert receipt["extracted"] == receipt["scored"] == 0


def test_mixed_selected_skipped_and_failed_assignment_is_fully_accounted():
    fake = FakeKubectl(
        stage_exits={("extractor", 0): 1},
        stage_selected={("extractor", 0): (IDS[0],)},
    )
    receipt = run_cohort(
        BatchConfig(limit=2, all_observed=True), kubectl=fake,
        run_id="funnel-mixed-accounting",
    )

    assert receipt["aggregate_receipts"]["extractor"] == {
        "selected": 1, "completed": 0, "failed": 1, "skipped": 1,
        "reported_chunks": 1, "chunk_count": 1, "complete": True,
    }
    assert receipt["skipped_counts"]["extractor"] == 1
    assert receipt["failures"] == [
        {"stage": "extractor", "failure": "JobFailed", "chunk": 0}
    ]


@pytest.mark.parametrize(
    "mutation", [
        "missing", "overlap", "outside", "duplicate", "wrong_count", "boolean_count",
    ],
)
def test_complete_assignment_rejects_invalid_identity_partitions(mutation):
    value = {
        "selected": 1, "scored": 1, "failed": 0, "skipped": 1,
        "selected_posting_ids": [IDS[0]], "skipped_posting_ids": [IDS[1]],
    }
    if mutation == "missing":
        value.pop("skipped_posting_ids")
    elif mutation == "overlap":
        value["skipped_posting_ids"] = list(IDS)
    elif mutation == "outside":
        value["skipped_posting_ids"] = ["00000000-0000-0000-0000-000000000099"]
    elif mutation == "duplicate":
        value["skipped_posting_ids"] = [IDS[1], IDS[1]]
    elif mutation == "wrong_count":
        value["skipped"] = 0
    else:
        value["skipped"] = True
    with pytest.raises(CoordinatorError, match="IncompleteReceipt"):
        _model_summary(json.dumps(value), "scored", posting_ids=IDS, limit=2)


def test_oversized_legacy_assignment_does_not_require_complete_partition():
    receipt = run_cohort(
        BatchConfig(limit=1), kubectl=FakeKubectl(), run_id="funnel-bounded-legacy",
    )
    assert receipt["failures"] == []
    for stage in ("extractor", "classifier"):
        summary = json.loads(receipt["jobs"][stage]["logs"])
        assert "selected_posting_ids" not in summary
        assert "skipped_posting_ids" not in summary


@pytest.mark.parametrize("stage,outcome", [("extractor", "extracted"), ("classifier", "scored")])
def test_all_observed_partial_summary_is_incomplete(stage, outcome):
    fake = FakeKubectl()
    def runner(command, **kwargs):
        result = fake(command, **kwargs)
        if command[1] == "logs" and "-c" in command:
            if command[command.index("-c") + 1] == stage:
                value = json.loads(result)
                value["selected"] -= 1
                value[outcome] -= 1
                return json.dumps(value)
        return result
    receipt = run_cohort(BatchConfig(limit=2, all_observed=True), kubectl=runner,
                         run_id="funnel-partial-summary")
    assert receipt["aggregate_receipts"][stage]["complete"] is False
    assert receipt["selected_counts"][stage] is None
    assert receipt[outcome] is None
    assert receipt["failures"] == [{"stage": stage, "failure": "IncompleteReceipt", "chunk": 0}]
    other, other_outcome = ("classifier", "scored") if stage == "extractor" else ("extractor", "extracted")
    assert receipt["aggregate_receipts"][other]["complete"] is True
    assert receipt["selected_counts"][other] == receipt[other_outcome] == len(IDS)
