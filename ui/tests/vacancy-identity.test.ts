import assert from "node:assert/strict";
import { test } from "node:test";
import { jdFingerprint, vacancyIdentity } from "../lib/vacancy-identity";
const identity = (url: string, raw_jd: string | null = null) => vacancyIdentity({url, apply_url: null, raw_jd});
test("requisition extraction recognizes NVIDIA, Workday and labelled JD IDs", () => {
  assert.deepEqual(identity("https://nvidia.wd5.myworkdayjobs.com/Careers/job/Haifa/Title_JR123-1").requisitions, ["JR123"]);
  assert.deepEqual(identity("https://employer.wd1.myworkdayjobs.com/Careers/job/City/Title_R45678/apply").requisitions, ["R45678"]);
  assert.deepEqual(identity("https://example.test", "Requisition ID: R789").requisitions, ["R789"]);
  assert.deepEqual(identity("https://example.test", "Workday requisition R456").requisitions, []);
  for (const url of ["bad", "https://example.test/careers", "https://linkedin.com/jobs/view/123"]) assert.deepEqual(identity(url).requisitions, []);
});
for (const [shape, url] of [
  ["Greenhouse jobs path", "https://boards.greenhouse.io/employer/jobs/123"],
  ["Greenhouse gh_jid", "https://example.test/careers?gh_jid=123"],
  ["Greenhouse embed token", "https://boards.greenhouse.io/embed/job_app?token=456"],
  ["Lever UUID", "https://jobs.lever.co/employer/12345678-1234-1234-1234-123456789abc"],
  ["Comeet position UID", "https://www.comeet.com/jobs/employer/12.345/JR123/engineer"],
  ["Workable shortcode", "https://apply.workable.com/employer/j/JR123/"],
]) {
  test(`${shape} is posting evidence, never a requisition`, () => {
    assert.deepEqual(identity(url).requisitions, []);
    assert.deepEqual(identity(url, "Requisition ID: R789").requisitions, ["R789"]);
  });
}
test("explicit JD labels retain employer IDs independently of ATS posting IDs", () => {
  for (const label of ["Req ID", "Requisition ID", "Job Req", "Req", "Requisition"]) {
    assert.deepEqual(identity("https://boards.greenhouse.io/employer/jobs/123", `${label}: ENG-456`).requisitions, ["ENG-456"]);
  }
});
const longBody = "Develop reliable software services. ".repeat(15);
const fingerprint = (body: string) => jdFingerprint(longBody + body);
test("JD fingerprint ignores formatting and bounded boilerplate while preserving role requirements", () => {
  assert.equal(fingerprint("**Build** reliable\nservices.\n\nWe are an equal opportunity employer."), fingerprint("Build   reliable services."));
  assert.notEqual(fingerprint("Build reliable services."), fingerprint("Build reliable services. Requires Rust."));
  assert.equal(jdFingerprint(" \n "), null);
  assert.equal(jdFingerprint("We are an equal opportunity employer."), null);
});
test("fingerprints retain technology punctuation and ambiguous requisitions remain explicit", () => {
  assert.notEqual(fingerprint("Requires C#"), fingerprint("Requires C"));
  assert.notEqual(fingerprint("Use foo_bar"), fingerprint("Use foobar"));
  assert.notEqual(fingerprint("Use vector<T>"), fingerprint("Use vector<U>"));
  assert.deepEqual(identity("https://example.test", "JR12345 and JR45678").requisitions, ["JR12345", "JR45678"]);
});

for (const text of ["FHIR R4", "S3/R2", "R2D2", "Python 3, R 4.2", "Cloudflare R2", "R123456", "JR1234"]) {
  test(`body technology or unlabelled short ID is not a requisition: ${text}`, () => {
    assert.deepEqual(identity("https://example.test", text).requisitions, []);
  });
}
test("Workday R IDs require five digits in the URL path and cannot come from query or body", () => {
  for (const url of [
    "https://employer.wd1.myworkdayjobs.com/Careers/job/City/Title_R456/apply",
    "https://employer.wd1.myworkdayjobs.com/Careers?req=_R45678",
    "https://example.test/Careers/job/City/Title_R45678",
  ]) assert.deepEqual(identity(url, "R45678").requisitions, []);
  assert.deepEqual(vacancyIdentity({url: "https://example.test", apply_url: "https://employer.wd1.myworkdayjobs.com/Careers/job/City/Title_R45678-1/apply"}).requisitions, ["R45678"]);
});

test("generic job labels are not requisition evidence", () => {
  for (const label of ["Job ID", "Job number", "Job no", "Job no."]) {
    assert.deepEqual(identity("https://example.test", `${label}: 979`).requisitions, []);
  }
});
test("JD requisitions matching a URL posting ID are ignored", () => {
  for (const url of [
    "https://boards.greenhouse.io/employer/jobs/12345",
    "https://example.test/careers?gh_jid=12345",
    "https://boards.greenhouse.io/embed/job_app?token=12345",
    "https://www.linkedin.com/jobs/view/engineer-12345/",
    "https://apply.workable.com/employer/j/JR12345/",
    "https://www.comeet.com/jobs/employer/12.345/JR12345/engineer",
    "https://example.test/jobs/%31%32%33%34%35",
  ]) {
    assert.deepEqual(identity(url, "Req ID: 12345. JR12345").requisitions, [], url);
  }
  assert.deepEqual(vacancyIdentity({url:"https://example.test",apply_url:"https://example.test/jobs/12345",raw_jd:"Req: 12345"}).requisitions, []);
  assert.deepEqual(identity("https://example.test/jobs/12345", "Req: 45678").requisitions, ["45678"]);
  assert.deepEqual(identity("https://example.test", "Apply at https://apply.workable.com/employer/j/JR12345/").requisitions, []);
});
test("fingerprints require at least 400 normalized role-body characters", () => {
  assert.equal(jdFingerprint("Apply now"), null);
  assert.equal(jdFingerprint("a".repeat(399)), null);
  assert.ok(jdFingerprint("a".repeat(400)));
  assert.equal(jdFingerprint("<p>" + "a".repeat(399) + "</p>\n\nWe are an equal opportunity employer."), null);
});
