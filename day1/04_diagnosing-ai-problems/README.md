# Diagnosing AI Problems · Session Materials

## What you're doing
You've received an email from Priya, a client whose AI-powered customer support system is misbehaving. Using the agent artifacts in this folder, your job is to diagnose what went wrong — without running any code.

## Main learning
How to read and interpret the components of an agentic system: system prompts, tool definitions, and execution traces. You'll practice the real-world skill of diagnosing AI failures from artifacts alone, the same way you'd approach a client escalation.

## What's in this folder

| File | What it is |
|------|-----------|
| `Priya_Email.pdf` | The client email describing the problem — start here |
| `system-prompt-coordinator.txt` | System prompt for the orchestrator agent |
| `system-prompt-subagent-account.txt` | System prompt for the account subagent |
| `system-prompt-subagent-billing.txt` | System prompt for the billing subagent |
| `system-prompt-subagent-technical.txt` | System prompt for the technical subagent |
| `coordinator-tools.json` | Tool schemas available to the coordinator |
| `subagent-account-tools.json` | Tool schemas for the account subagent |
| `subagent-billing-tools.json` | Tool schemas for the billing subagent |
| `subagent-technical-tools.json` | Tool schemas for the technical subagent |
| `trace-T-4471-coordinator.json` | Execution trace for the coordinator on ticket T-4471 |
| `trace-T-4471-subagent-account.json` | Execution trace for the account subagent on T-4471 |

## No code to run
This is a read-and-diagnose exercise. Open the PDF first, then work through the system prompts and traces to identify the root cause.
