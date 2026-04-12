# AI-Assisted Development: Best Practices Guide

> A practical guide for engineering teams using AI coding assistants (Claude, GitHub Copilot, Cursor, ChatGPT, Gemini, etc.)

---

## Table of Contents

1. [Mindset: What AI Is and Isn't](#1-mindset-what-ai-is-and-isnt)
2. [Cost & Usage Efficiency](#2-cost--usage-efficiency)
3. [Prompting Effectively](#3-prompting-effectively)
4. [Code Quality & Review](#4-code-quality--review)
5. [Security](#5-security)
6. [Context Management](#6-context-management)
7. [Team Collaboration](#7-team-collaboration)
8. [When NOT to Use AI](#8-when-not-to-use-ai)
9. [Workflow Integration](#9-workflow-integration)
10. [Tool-Specific Tips](#10-tool-specific-tips)
11. [Measuring Productivity](#11-measuring-productivity)

---

## 1. Mindset: What AI Is and Isn't

### AI is a junior developer with infinite patience, not a senior architect

| AI Is Good At | AI Struggles With |
|---------------|-------------------|
| Boilerplate and scaffolding | Understanding your business logic |
| Explaining unfamiliar code | Long-term project memory |
| Suggesting patterns and idioms | Knowing what NOT to build |
| Writing tests for known behavior | Catching subtle domain-specific bugs |
| Refactoring isolated functions | Cross-cutting architectural decisions |
| Documentation | Understanding deadlines and tradeoffs |

### The Golden Rule

> **You are responsible for every line of code you commit — whether you wrote it or AI did.**

AI-generated code is not automatically correct, secure, or appropriate for your use case. Review it with the same scrutiny you would apply to a pull request from a new team member.

### Avoid "AI Blindness"

A well-written AI response *looks* authoritative. This creates a bias to accept it without critical evaluation. Consciously slow down when reviewing AI output, especially for:
- Security-sensitive code
- Database queries and migrations
- Business logic with financial or legal implications
- Infrastructure and deployment configuration

---

## 2. Cost & Usage Efficiency

### Subscription Tiers (General)

Most AI tools offer tiered plans. None are truly "unlimited" — they have rate limits and usage quotas that increase with price. Common tiers:

- **Free** — Very limited, suitable for occasional use
- **Individual Pro** (~$20/mo) — Daily use, moderate sessions
- **Team/Max** (~$90–100/mo) — Heavy use, long agentic sessions, priority access

### Token Economics

Every message, file read, and response consumes tokens. Long conversations are expensive. Key costs:
- System prompts loaded at session start
- All prior messages in the conversation (context window)
- Every file the AI reads during the session
- Every response the AI generates

### Efficiency Rules

**Start fresh sessions for each distinct task**
- Continuing a long session doesn't make the AI smarter — it just costs more
- Use `/clear` or start a new chat when switching topics

**Be specific, not exploratory**
- Bad: "Look at my project and suggest improvements"
- Good: "In `src/auth/middleware.py`, the token validation logic has a race condition when multiple requests arrive simultaneously — fix it"

**Point to exact files and line numbers**
- Every file search or codebase exploration burns tokens
- "Edit `services/payment.ts` line 142" is cheaper than "find where payments are processed"

**Use a `CLAUDE.md` / project context file**
- A single file at the root of your project describing architecture, key files, conventions, and domain context
- The AI reads this once instead of exploring your codebase every session
- Saves time and tokens; makes responses more accurate immediately

Example structure:
```markdown
# Project: [Name]

## Architecture Overview
[Brief description of system components]

## Key Entry Points
- `src/main.py` — Application entry point
- `src/api/` — REST API handlers

## Domain Context
[Business-specific terminology the AI should know]

## Conventions
- We use snake_case for Python, camelCase for TypeScript
- All API errors must use the ErrorResponse class in `src/models/errors.py`
```

**Avoid asking for full rewrites**
- Targeted edits are far cheaper than regenerating entire files
- "Change the retry logic in this function" beats "Rewrite this module"

---

## 3. Prompting Effectively

### The Anatomy of a Good Prompt

```
[Context] + [Specific Task] + [Constraints] + [Output Format]
```

**Example — Bad prompt:**
> "Fix my authentication"

**Example — Good prompt:**
> "In `src/auth/jwt.py`, the `validate_token()` function does not handle expired tokens — it raises an unhandled exception instead of returning a 401. Fix it to return `(False, 'token_expired')` and add a unit test for this case. Do not change the function signature."

### Prompting Techniques

**Give constraints upfront**
- "Do not add new dependencies"
- "Keep the public API unchanged"
- "This must work without a database connection"
- "Performance matters more than readability here"

**Use step-by-step for complex tasks**
> "First read the file. Then explain what the current logic does. Then propose a fix. Wait for my approval before making changes."

**Ask for reasoning before code**
> "Before writing any code, explain your approach and the tradeoffs."

**Request alternatives**
> "Give me two approaches to this — one prioritizing simplicity, one prioritizing performance."

**Specify what you don't want**
> "Fix the bug without refactoring unrelated code. Don't add logging or comments I didn't ask for."

### Common Prompt Patterns

| Goal | Prompt Pattern |
|------|---------------|
| Understand code | "Explain what `[function]` does, step by step, assuming I don't know the codebase" |
| Find a bug | "This function is supposed to do X but does Y in edge case Z. What's wrong?" |
| Write tests | "Write unit tests for `[function]`. Cover: happy path, empty input, and invalid types" |
| Code review | "Review this diff for bugs, security issues, and style violations. Be critical." |
| Refactor | "Refactor `[function]` to eliminate duplication. Do not change behavior." |
| Documentation | "Write a docstring for this function explaining parameters, return value, and side effects" |

---

## 4. Code Quality & Review

### Never Merge AI Code Without Review

Treat AI-generated code like a PR from a junior developer. Always check:

- **Does it actually solve the problem?** Run it, don't just read it.
- **Does it handle edge cases?** Empty inputs, nulls, large values, concurrent access.
- **Does it match project conventions?** Naming, structure, error handling patterns.
- **Does it introduce unnecessary complexity?** AI often over-engineers simple problems.
- **Does it add unwanted scope?** AI frequently adds features you didn't ask for.

### Common AI Code Anti-Patterns to Watch For

**Over-engineering**
- AI loves abstractions, design patterns, and configurability — even when a simple function suffices
- Watch for unnecessary factory classes, excessive generics, and premature optimization

**Dead code**
- AI sometimes generates helper functions or imports it never uses
- Always check for unused code before committing

**Hallucinated APIs**
- AI will sometimes call methods or use library features that don't exist or have changed
- Verify any unfamiliar function calls against actual documentation

**Incorrect error handling**
- Silent catches (`except: pass`), swallowing errors, or logging without re-raising
- Make sure errors are handled appropriately for your system's needs

**Inadequate tests**
- AI-written tests often only test the happy path
- Check that tests actually assert meaningful behavior, not just that the function runs

**Copy-paste duplication**
- When generating multiple similar functions, AI may copy-paste instead of abstracting
- Review for DRY violations

### Incremental Review Workflow

For large changes, don't let AI make everything at once:

1. Ask AI to **plan** the changes first
2. Review and approve the plan
3. Ask AI to implement **one section at a time**
4. Review and test each section before proceeding

---

## 5. Security

### Critical: Never Share Secrets with AI

**Do not paste into AI chat sessions:**
- API keys, tokens, passwords
- Private keys or certificates
- Database connection strings with credentials
- `.env` files or configuration with real values
- PII (personal identifiable information) of users
- Proprietary business data

**Use placeholders instead:**
```python
# Instead of sharing your real key:
API_KEY = "sk-real-key-here"

# Share this:
API_KEY = "YOUR_API_KEY_HERE"
```

Most enterprise AI tools (especially cloud-based ones) log conversations for model improvement unless you have a specific enterprise agreement. Treat AI chat like a public forum.

### Security Review Checklist for AI-Generated Code

- [ ] **Injection vulnerabilities** — SQL injection, command injection, XSS
- [ ] **Input validation** — Is user input sanitized at system boundaries?
- [ ] **Authentication/Authorization** — Are endpoints properly protected?
- [ ] **Secrets management** — Are secrets hardcoded anywhere?
- [ ] **Dependency security** — Are newly suggested packages well-maintained and trusted?
- [ ] **Cryptography** — Is AI using standard, non-deprecated algorithms correctly?
- [ ] **Error messages** — Do errors leak internal implementation details?
- [ ] **Rate limiting** — Are new endpoints protected against abuse?

### AI and Dependency Management

When AI suggests adding a new library:
- Check the package's download count and last update date
- Verify it's the official package (typosquatting is common: `reqeusts` vs `requests`)
- Check for known CVEs (use `pip audit`, `npm audit`, `snyk`, etc.)
- Evaluate whether the dependency is actually necessary

### Sensitive Code Patterns to Manually Verify

Always manually review AI-generated code for:
- Authentication and session management
- Payment processing
- File upload handling
- Database queries with user-supplied parameters
- Any subprocess or shell execution
- Serialization/deserialization of external data

---

## 6. Context Management

### How AI Context Works

AI models have a "context window" — a limit on how much text they can "see" at once. In a long conversation:
- Older messages may be summarized or dropped
- The AI may "forget" details from earlier in the session
- Performance and accuracy can degrade

### Strategies to Manage Context

**Keep sessions task-scoped**
- One conversation per feature/bug/task
- Start fresh when moving to a different problem

**Summarize before switching topics**
- "Before we move on, summarize the decisions we made in this session"
- Save important decisions as comments in code or in a notes file

**Re-anchor the AI when sessions get long**
- "As a reminder, we're working on X, the constraint is Y, and the agreed approach is Z"
- This prevents drift and keeps responses relevant

**Use structured project context files**
- Keep a `CLAUDE.md`, `AI_CONTEXT.md`, or similar file updated with:
  - Architecture decisions
  - Key conventions
  - Gotchas and known issues
  - Glossary of domain terms

---

## 7. Team Collaboration

### Establish Team Standards

Create a shared document (or section in your engineering handbook) covering:
- Which AI tools are approved for use
- What types of code/data can be shared with AI
- Required review process for AI-generated code
- How to label AI-generated code in PRs (optional but useful)

### PR and Code Review Practices

**Label AI-assisted PRs** (optional, but increases transparency)
- Add a tag or note in the PR description: "Parts of this were AI-generated and reviewed"
- Helps reviewers know where to focus scrutiny

**Don't use AI to rubber-stamp reviews**
- Asking AI "is this PR good?" is less valuable than asking "what edge cases does this PR miss?"
- Use AI for specific review questions, not blanket approval

**Consistent prompting across the team**
- Share effective prompts in a team wiki or Slack channel
- A prompt that solves a recurring problem once should be documented for reuse

### Knowledge Sharing

- Run occasional team demos: "Here's a workflow that saved me 2 hours"
- Document AI-assisted approaches that worked well in your post-mortems or retros
- Share examples of AI-generated code that required significant correction — these are valuable learning moments

### AI Should Not Replace Code Ownership

- Every piece of code should have a human owner who understands it
- "The AI wrote it" is not an acceptable answer when debugging production incidents
- Rotate ownership of AI-generated modules through normal code review and pairing

---

## 8. When NOT to Use AI

### High-Risk Scenarios

**Critical path business logic**
- Core financial calculations, pricing algorithms, compliance rules
- These require deep domain understanding that AI lacks
- AI can assist but a domain expert must own and verify

**Database schema migrations**
- Migrations are hard to reverse and affect all environments
- AI can draft them but a senior engineer should plan and review carefully

**Security-critical systems**
- Auth flows, encryption, access control
- Get a security review regardless of whether AI was involved

**Novel architecture decisions**
- AI is trained on existing patterns — it will suggest common solutions
- For genuinely novel or business-specific architecture, AI input is a starting point at best

### When AI Slows You Down

Sometimes it's faster to just write the code:
- Simple, well-understood functions you've written before
- Small fixes where reading and prompting takes longer than typing
- Tasks where you already know exactly what to do

Don't feel obligated to use AI for everything. It's a tool, not a mandate.

---

## 9. Workflow Integration

### Effective Daily Workflow

```
1. Open a new AI session for the task
2. Paste your CLAUDE.md / project context (or let the tool read it automatically)
3. Describe the task with constraints
4. Ask for a plan before any code
5. Review and approve the plan
6. Implement incrementally, reviewing each step
7. Run tests and verify behavior
8. Close the session — don't leave it open "just in case"
```

### Using AI for Different Task Types

**Debugging**
- Paste the error message, relevant stack trace, and the specific function
- Ask: "What could cause this error in this code?"
- Don't paste your entire codebase

**Code Review**
- Paste only the diff or changed functions
- Ask specific questions: "What edge cases does this miss?" / "Are there security issues?"

**Writing Tests**
- Provide the function signature, docstring, and a description of intended behavior
- Ask for tests covering: happy path, boundary conditions, error cases
- Review that tests actually test behavior, not just that code runs

**Documentation**
- Paste the function/module and ask for documentation
- Specify format: docstring, README section, API docs, etc.

**Learning Unfamiliar Code**
- Ask the AI to explain a function or module step by step
- Follow up with "what would happen if X?" to deepen understanding
- This is one of AI's most valuable uses

### Agentic / Autonomous Workflows

When using AI in "agentic" mode (where it can read/write files, run commands, etc.):

- **Review before large operations** — Ask it to explain what it's about to do
- **Commit frequently** — Before any significant AI-driven change, commit your current state so you can roll back
- **Don't leave it unsupervised on critical systems** — Watch what it's doing, especially with files and shell commands
- **Set clear scope boundaries** — "Only edit files in `src/utils/`, do not touch `src/api/`"

---

## 10. Tool-Specific Tips

### Claude Code (CLI)

- Use `CLAUDE.md` at project root for persistent project context
- `/clear` resets conversation context — use it between unrelated tasks
- `/compact` compresses history to save tokens mid-session
- Start new sessions for new tasks rather than continuing old ones
- Be explicit about file paths to avoid unnecessary codebase exploration

### GitHub Copilot

- Write descriptive function names and docstrings — Copilot uses these as context
- Accept suggestions incrementally (tab); don't accept large blocks blindly
- Use Copilot Chat for explanation and review, not just generation
- Disable for sensitive files (`.env`, credentials) via `.copilotignore`

### Cursor

- Use `@file` and `@symbol` references to scope context precisely
- Rules files (`.cursorrules`) function like `CLAUDE.md` — set up project conventions there
- Use Composer for multi-file changes, Chat for questions
- Review diffs carefully in Composer before applying

### ChatGPT / Claude Web

- Not ideal for large codebases — context limits are more restrictive in chat interfaces
- Best for: explaining concepts, reviewing isolated functions, writing templates
- Always use Code Interpreter / Artifacts for code — it formats better and is easier to copy

### All Tools

- Keep a personal "prompt library" of prompts that work well for recurring tasks
- Use temperature settings if available — lower temperature (more deterministic) for code
- Don't trust AI for up-to-date library documentation — always verify against official docs

---

## 11. Measuring Productivity

### How to Know If AI Is Helping

Track informally:
- **Time per PR** — Are features shipping faster?
- **Bug rate in AI-assisted code** — More or fewer bugs reaching review/production?
- **Review time** — Are AI-generated PRs taking longer to review (a cost) or shorter?
- **Developer satisfaction** — Is the team less fatigued on boilerplate tasks?

### Red Flags

Watch for these signs that AI usage is costing more than it saves:
- PRs with AI-generated code take significantly longer to review
- Bugs are being introduced in areas AI touched
- Developers are copying AI output without understanding it
- Team members are spending more time prompting than coding
- "The AI did it" being used as an explanation in incident post-mortems

### The Right Benchmark

AI assistance should feel like having a capable pair programmer available at all times. If it feels like babysitting an intern who keeps going off-script, revisit your prompting and review workflow.

---

## Quick Reference Card

```
DO:
✓ Review every line of AI-generated code
✓ Start fresh sessions per task
✓ Point to exact files and functions
✓ Ask for a plan before code
✓ Commit before large AI-driven changes
✓ Use project context files (CLAUDE.md)
✓ Run tests on AI-generated code
✓ Be specific about constraints

DON'T:
✗ Paste API keys, passwords, or PII into AI chat
✗ Merge AI code without understanding it
✗ Let long sessions accumulate unbounded context
✗ Trust AI for up-to-date library documentation
✗ Use AI for irreversible operations without review
✗ Let "AI wrote it" replace code ownership
✗ Accept large code blocks without line-by-line review
✗ Use AI as a rubber stamp for security decisions
```

---

*Last updated: April 2026 | Contribute updates via PR*
