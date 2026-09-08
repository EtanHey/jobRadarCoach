import assert from "node:assert/strict";
import { test } from "node:test";
import { experiencePhrase, postingUrl, technologyMentions, titleSeniority } from "../lib/job-metadata";

test("Workable export URLs become a human page without changing other hosts", () => {
  assert.equal(postingUrl("https://apply.workable.com/example/jobs/view/ABC123.md"), "https://apply.workable.com/example/j/ABC123/");
  assert.equal(postingUrl("https://apply.workable.com/example/j/ABC123/apply"), "https://apply.workable.com/example/j/ABC123/apply");
  assert.equal(postingUrl("https://example.test/example/jobs/view/ABC123.md"), "https://example.test/example/jobs/view/ABC123.md");
});

test("seniority is explicit title evidence; unspecified titles stay unknown", () => {
  assert.equal(titleSeniority("Senior Backend Engineer"), "Senior");
  assert.equal(titleSeniority("Junior Fullstack Engineer"), "Junior");
  assert.equal(titleSeniority("Software Engineer"), null);
  assert.equal(titleSeniority("Staff Engineer"), "Staff / Principal");
});

test("experience quotes requirements and does not turn company age into experience", () => {
  assert.equal(experiencePhrase("Founded 20 years ago. You need 3+ years of experience in TypeScript."), "3+ years of experience");
  assert.equal(experiencePhrase("5–7 years professional experience"), null);
  assert.equal(experiencePhrase("Our company is 25 years old."), null);
  assert.equal(experiencePhrase(null), null);
});

test("experience requires applicant context and rejects company, negated, and wishful prose", () => {
  assert.equal(experiencePhrase("Our company has 20 years of experience serving customers."), null);
  assert.equal(experiencePhrase("No 5 years of experience required; strong projects are enough."), null);
  assert.equal(experiencePhrase("It would be nice to have 4 years of relevant experience."), null);
  assert.equal(experiencePhrase("Our company has at least 20 years of experience serving customers."), null);
  assert.equal(experiencePhrase("5 years of experience is not required."), null);
  assert.equal(experiencePhrase("Minimum of 2 years commercial experience."), "2 years commercial experience");
  assert.equal(experiencePhrase("Requirements:\n- 3+ years of hands-on experience building APIs"), "3+ years of hands-on experience");
});

test("bare company-tenure prose stays unknown unless an applicant heading is active", () => {
  assert.equal(experiencePhrase("20 years of experience serving customers."), null);
  assert.equal(experiencePhrase("- 20 years of experience serving customers."), null);
  assert.equal(experiencePhrase("## Requirements\n- 3+ years of experience building APIs"), "3+ years of experience");
  assert.equal(experiencePhrase("## Requirements\nStrong communication\n## Our story\n20 years of experience serving customers."), null);
  assert.equal(experiencePhrase("Qualifications:\n- 5–7 years professional experience"), "5–7 years professional experience");
  assert.equal(experiencePhrase("Requirements:\nStrong communication\nAbout Company\n20 years of experience serving customers."), null);
});

test("experience covers real required phrasing around years, role, and action", () => {
  assert.equal(experiencePhrase("Required\n5+ years building and operating production backend services"), "5+ years building");
  assert.equal(experiencePhrase("Your Experience\n8+ years in software engineering with a full-stack background"), "8+ years in software engineering");
  assert.equal(experiencePhrase("We are seeking a developer with 3–5 years of hands-on experience working across the stack."), "3–5 years of hands-on experience");
  assert.equal(experiencePhrase("You Bring\n4+ years of full-stack development experience"), "4+ years of full-stack development experience");
  assert.equal(experiencePhrase("Qualifications\nExperience of at least 2 years in software development."), "at least 2 years in software development");
  assert.equal(experiencePhrase("Required Qualifications • 7+ years of professional, hands-on experience building production software"), "7+ years of professional, hands-on experience");
  assert.equal(experiencePhrase("5+ years professional backend engineering, with distributed systems depth"), "5+ years professional backend engineering");
  assert.equal(experiencePhrase("What you'll need: 5+ years of experience managing business-critical teams"), "5+ years of experience");
  assert.equal(experiencePhrase("Minimum qualifications: 10 years of experience working with hardware verification languages"), "10 years of experience");
  assert.equal(experiencePhrase("What You Bring Required Qualifications • 8+ years of experience as a software engineer"), "8+ years of experience");
  assert.equal(experiencePhrase("Work closely with the team to strengthen our culture. What You Bring Required Qualifications • 8+ years of experience as a software engineer"), "8+ years of experience");
  assert.equal(experiencePhrase("Team standards. 4+ years of hands-on software development. Practical security experience."), "4+ years of hands-on software development");
  assert.equal(experiencePhrase("Required\n8+ Years of hands-on software development and architecture experience. Proven experience leading teams."), "8+ Years of hands-on software development and architecture experience");
});

test("preferred years and non-applicant durations are not required experience", () => {
  assert.equal(experiencePhrase("Minimum Qualifications\n7+ years of manufacturing experience preferred."), null);
  assert.equal(experiencePhrase("Nice to Have:\n6+ years of backend engineering experience."), null);
  assert.equal(experiencePhrase("Paid sabbatical after 5 years for employees to recharge."), null);
  assert.equal(experiencePhrase("Our team combines 20 years of software development experience."), null);
});

test("technology aliases stay explicit and avoid prose and substring collisions", () => {
  assert.deepEqual(
    technologyMentions("Tech stack: React Native, NodeJS, K8s, Amazon Web Services, Google Cloud Platform, MongoDB, Redis, Kafka, Terraform, GitHub Actions, Linux, and Golang."),
    ["React Native", "Node.js", "Kubernetes", "AWS", "GCP", "Go", "MongoDB", "Redis", "Kafka", "Terraform", "GitHub Actions", "Linux"],
  );
  assert.deepEqual(technologyMentions("Go to our website. JavaScript experience required."), ["JavaScript"]);
  assert.deepEqual(technologyMentions("Programming languages: Go, JavaScript and Java."), ["JavaScript", "Go", "Java"]);
  assert.deepEqual(technologyMentions("Please express interest this spring."), []);
  assert.deepEqual(technologyMentions("Backend services use Spring Boot and Express.js."), ["Spring", "Express"]);
});
