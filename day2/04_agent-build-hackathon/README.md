# Agent Build Hackathon · MiniHack

## What you're building
An AI agent that automates RFP (Request for Proposal) responses for a cybersecurity vendor. Working in teams of 3–4, you'll build an agent that parses a questionnaire into categorized questions, retrieves relevant material from a knowledge base, and generates structured answers — then iterate to improve quality.

## Main learning
How to design and build a multi-step agentic system under time pressure, the way you would in a real AAI engagement. You'll make real tradeoffs on tool design, retrieval strategy, and output quality — and defend your decisions in the debrief.

## What's in this folder

| File | What it is |
|------|-----------|
| `Agent_Engineering_Challenge.ipynb` | The main hackathon notebook — start here |
| `dry-run-test.py` | Facilitator dry-run script to validate the notebook end-to-end |
| `dry-run-output.txt` | Expected output from the dry-run (reference for facilitators) |

---

## How to run

### Option 1 — GitHub Codespaces (no local install needed)

1. Go to the repo on GitHub and click the green **Code** button.
2. Select the **Codespaces** tab and click **Create codespace on main**.
3. Wait for the environment to load (takes about a minute).
4. Open `day2/04_agent-build-hackathon/Agent_Engineering_Challenge.ipynb`.
5. When prompted to select a kernel, choose **Python 3**.
6. In the API key cell, paste your key between the quotes.
7. Run cells with **Shift+Enter** or use **Run All** from the top menu.

---

### Option 2 — VS Code locally

1. Open VS Code and go to **File → Open Folder**, select this folder.
2. Install the **Python** and **Jupyter** extensions if prompted.
3. Open `Agent_Engineering_Challenge.ipynb` and select your Python environment as the kernel.
4. Open a terminal (**Terminal → New Terminal**) and set your API key:
   ```bash
   export ANTHROPIC_API_KEY=your_key_here
   ```
5. Run cells with **Shift+Enter** or click **Run All**.

---

### Option 3 — Jupyter locally

1. Install Jupyter if needed: `pip install notebook`
2. Open a terminal, navigate to this folder, and set your API key:
   ```bash
   export ANTHROPIC_API_KEY=your_key_here
   cd path/to/day2/04_agent-build-hackathon
   jupyter notebook Agent_Engineering_Challenge.ipynb
   ```
3. Run cells with **Shift+Enter** or use **Cell → Run All**.
