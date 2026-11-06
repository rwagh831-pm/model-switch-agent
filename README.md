# Model Switch Agent

**Should my app switch to the AI model that just came out? This agent answers with tests, not hype.**

New models launch every few weeks, and each one claims to be better or cheaper. Benchmarks don't tell you whether it's better at *your* task. Testing by hand takes time, and asking a chatbot gives an opinion, not evidence.

The answer is usually **Stay**, and that matters. A switch you didn't need costs money, and a bad switch costs quality.

## How it works

| Step | Who | What happens |
|---|---|---|
| 1. Lock the rules | You, before any test | Rules and test answers are fingerprinted (SHA-256). If anything changes, tests refuse to run |
| 2. Read the release | **Agent** (Claude Agent SDK) | Reads the official release page and decides: test, skip or unclear |
| 3. Check the agent | Code | Every quote must appear word for word in a page the agent fetched, or the decision is rejected |
| 4. Run the tests | Code | The same 30 questions on the current model and the new one, 3 runs each |
| 5. Score | Code | Correct answers, invented facts, failed calls, cost and speed. The worst run counts |
| 6. Verdict | Code | SWITCH, STAY or TEST_MORE from the locked rules |
| 7. Decide | You | The agent never changes any live setting |

**Why only step 2 uses AI:** release pages are written differently every time, and what to read next depends on what the last page said. Everything that decides the result is plain code, so a model can't talk its way to a better score.

## Results (real runs, version 2)

### Agent: reading the real Claude Sonnet 5.5 page
**Decision: skip.** "The page lists Sonnet 5.5 at $2 / $10 per MTok, while the same page lists Claude Haiku 5.5 at 'From $0.10 / $0.50' ... it gives no reason to expect a gain that would justify the higher cost." 3 quotes, all verified on the page. Cost: $0.0014.

### Test: Claude Haiku 5.5 (current) vs Claude Sonnet 5.5
| Model | Worst run | Each run | Invented facts | Cost per run | Median per call |
|---|---|---|---|---|---|
| Claude Haiku 5.5 | 30/30 | 30, 30, 30 | 0 | $0.0029 | 1.13 s |
| Claude Sonnet 5.5 | 30/30 | 30, 30, 30 | 0 | $0.0579 | 1.83 s |

**Verdict: STAY.** Same score at about 20 times the cost. The agent's "skip" was right, and it cost about 40 times less than running this test.

### Test: Claude Haiku 5.5 (current) vs local llama3.1 (free, on my laptop)
| Model | Worst run | Each run | Invented facts | Cost per run | Median per call |
|---|---|---|---|---|---|
| Claude Haiku 5.5 | 30/30 | 30, 30, 30 | 0 | $0.0029 | 1.13 s |
| llama3.1 (local) | 27/30 | 27, 29, 28 | 0 | free | 5.19 s |

**Verdict: STAY.** In its worst run, llama3.1 marked PAN and Aadhaar as "skip" instead of asking the applicant. That could leave a required field empty. It also answered the prompt-injection question in plain text instead of JSON, which would break a real form. It was free, but about 4.6 times slower. This is the case version 1 got wrong: version 1 said SWITCH.

## What broke, and how I fixed it

Version 1 gave a **wrong recommendation**. Its results are kept unchanged in `results/v1/`.

| Problem | How I found it | Fix in version 2 |
|---|---|---|
| I typed the list of "allowed" numbers by hand and left out the pay figures. Haiku correctly mentioned her real pay and was marked as inventing facts | I read every answer marked wrong instead of trusting the score | Allowed numbers are read from the profile automatically, with a test for this exact bug |
| A local model **4.5 times slower** got "SWITCH" because it was free | The verdict didn't match common sense | New locked rule: stay if the new model is more than 2 times slower |
| Haiku scored 30/30 in one run and 29/30 in another | Comparing runs | Each model runs 3 times and the worst run counts |

The bug flipped the verdict from STAY to SWITCH. A score is only as good as the answer key behind it.

## Safety checks

| Check | What it stops |
|---|---|
| Rules locked by SHA-256 fingerprint before testing | Choosing rules after seeing results |
| Quotes must appear word for word in a fetched page | Invented prices or features |
| Agent can fetch only https pages on the named site, 4 at most | Wandering the web, or being pointed at internal addresses |
| Agent has no file, shell or settings tools (`tools=[]`) | Changing anything on the machine |
| `max_turns=10`, `max_budget_usd=0.25` | Endless loops and overspending |
| Web pages wrapped as untrusted data; a test question tries prompt injection | A page or form giving the model orders |
| A fictional applicant only | Personal data going public |
| API keys only in `.env`, which git ignores | Leaked keys |
| No automatic fallback to another Claude model | Measuring a different model than the one named |

## Proving the tests can catch failure

Offline, at no cost, `python -m pytest` runs 25 tests, including:
- a **fake lying model** that invents facts: it scores 0/30 and gets STAY
- a **fake broken model** whose calls all fail: it gets TEST_MORE
- tests that recreate both version 1 bugs

## Limitations (honest)

- **Small, single task:** 30 questions about filling job forms. Results don't carry over to other tasks.
- **The test is too easy for current Claude models.** Both scored 30/30, so this set can't separate them. Harder questions are the next step.
- **I wrote and labelled the questions myself.** No second person checked them.
- **The invented-fact check is a filter, not a verdict.** It catches invented numbers and company names, but not every false claim.
- **Lenient JSON reading:** the scorer accepts JSON anywhere in a reply. Sonnet once wrote a paragraph before its JSON and still passed.
- **The lock is evidence, not proof.** Fingerprints catch changes, and the lock files record when rules were set. These first runs happened before the project was in git, so nothing independently proves those times. Future tests should commit the lock before running.
- **No outside users yet.** It has been used only by me.
- Claude prices come from Anthropic's published table, cached on 2026-10-06.

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # then add your own ANTHROPIC_API_KEY
python -m pytest            # offline, free
python run.py lock
python run.py compare --current claude:claude-haiku-5-5 --candidate claude:claude-sonnet-5-5
python run.py assess --url https://platform.claude.com/docs/en/models/sonnet-5-5/overview
python run.py decide --url <release page> --current <model> --candidate <model>
```

Models are written as `provider:model`: `claude:`, `groq:`, `ollama:` (local), or `stub:` (fake models for testing).

## Built with

Python, Claude Agent SDK (the agent), Anthropic Python SDK (test calls), Claude Haiku 5.5 and Sonnet 5.5, local llama3.1 via Ollama.

Built by Rahul Wagh with Claude Code. I chose the problem, set and approved the decision rules and test answers, and decided how to handle the version 1 failure. Claude Code wrote the code and found the version 1 bug while reviewing the answers. I can explain every part.
