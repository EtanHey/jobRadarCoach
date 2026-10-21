import assert from "node:assert/strict";
import { test } from "node:test";
import { jdFingerprint, vacancyIdentity } from "../lib/vacancy-identity";
const identity = (url: string, raw_jd: string | null = null) => vacancyIdentity({url, apply_url: null, raw_jd});
test("requisition extraction recognizes NVIDIA, Workday, Greenhouse and labelled JD IDs", () => {
  assert.deepEqual(identity("https://nvidia.wd5.myworkdayjobs.com/Careers/job/Haifa/Title_JR123-1").requisitions, ["JR123"]);
  assert.deepEqual(identity("https://employer.wd1.myworkdayjobs.com/Careers/job/City/Title_R456/apply").requisitions, ["R456"]);
  assert.deepEqual(identity("https://boards.greenhouse.io/employer/jobs/123?utm_source=x").requisitions, ["123"]);
  assert.deepEqual(identity("https://example.test/careers?gh_jid=123").requisitions, ["123"]);
  assert.deepEqual(identity("https://boards.greenhouse.io/embed/job_app?token=456").requisitions, ["456"]);
  assert.deepEqual(identity("https://example.test", "Requisition ID: R789").requisitions, ["R789"]);
  for (const url of ["bad", "https://example.test/careers", "https://linkedin.com/jobs/view/123"]) assert.deepEqual(identity(url).requisitions, []);
});
test("JD fingerprint ignores formatting and bounded boilerplate while preserving role requirements", () => {
  assert.equal(jdFingerprint("**Build** reliable\nservices.\n\nWe are an equal opportunity employer."), jdFingerprint("Build   reliable services."));
  assert.notEqual(jdFingerprint("Build reliable services."), jdFingerprint("Build reliable services. Requires Rust."));
  assert.equal(jdFingerprint(" \n "), null);
  assert.equal(jdFingerprint("We are an equal opportunity employer."), null);
});
test("fingerprints retain technology punctuation and ambiguous requisitions remain explicit", () => {
  assert.notEqual(jdFingerprint("Requires C#"), jdFingerprint("Requires C"));
  assert.notEqual(jdFingerprint("Use foo_bar"), jdFingerprint("Use foobar"));
  assert.notEqual(jdFingerprint("Use vector<T>"), jdFingerprint("Use vector<U>"));
  assert.deepEqual(identity("https://example.test", "JR123 and JR456").requisitions, ["JR123", "JR456"]);
});
