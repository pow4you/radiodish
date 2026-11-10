# How the learning environment works
I'll act as your technical advisor, not your lecturer.

The rules:
1. You do the implementation. I won't write the solution before you've attempted it.
2. Tasks have objectives, not recipes. You get acceptance criteria, not a sequence of commands to copy.
3. You can experiment. Breaking things is an expected part of the course.
4. Ask for hints when stuck. I'll give progressively more specific hints rather than immediately solving everything.
5. Code reviews are constructive. I'll review your decisions, explain trade-offs and point out potential problems.
6. You own the result. The goal is being able to explain and maintain your work without me.
You can work independently for as long as you like. There are no deadlines.


# Lab 01: Take ownership
Available now

Estimated time: 20–40 minutes · Difficulty: Introductory

## Scenario

You've inherited a GitHub Actions workflow. It works, but you didn't write it. Your job is to understand it well enough to modify it safely.

Repository: pow4you/radiodish

Your mission:

## Part A — Investigation

Open .github/workflows/ci.yml.

Figure out:
- What events trigger the workflow?

push to main and release type publish
but publis Only runs on release, test runs on both. Thats what the if flag is for.
any pr

- How many jobs exist?

One job called test with 7 steps
another job called publish with 6 steps

- Which job depends on another?

publish depends on test, as specifyed with the needs flag

- Where does the runner get its Python installation?

    uses: actions/setup-python@v5
        with:
          python-version: "3.13"

- Why does the publishing job have additional permissions?

I think it is because it builds something and would write its results to the release so it needs access. the other action only reads and doesnt produce anything on its own

- What happens if pytest fails?

github shows fail for the commit

## Part B — Experiment

Modify the workflow so that it can also be started manually from GitHub's Actions interface.

Requirements:
- Existing triggers must continue working.
- You must be able to trigger it manually.
- The manually triggered run must still execute the normal test and build process.
- Verify that it works in GitHub.
  
Added 
```
on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:
  release:
    types: [published]
``` 
and 
```
  publish:
    name: Publish to PyPI
    if: github.event_name == 'release' || github.event_name == 'workflow_dispatch'
```

## Part C — Reflection

Answer these three questions:
1. What was the most surprising thing you discovered?

that it doesnt block the commit. which now writing this feels like a stupid thing to wonder about because commits are allowed to break things, PRs aren't

2. What did you have to look up?

how to add workflow dispatch to the `if` in build

3. What would you change about the workflow if you were responsible for maintaining it?
   
This one? idk. i feel like i know too little rn.