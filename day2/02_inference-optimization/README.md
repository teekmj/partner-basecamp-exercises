# Inference Optimization · Build-Along

## What you're doing
A hands-on lab benchmarking Claude models across the key metrics that matter in production: time to first token (TTFT), time to completion (TTC), output tokens per second (OTPS), and cost. You'll then explore how prompt caching and tool use affect those numbers.

## Main learning
How to measure and optimize inference for real deployments. You'll compare Haiku, Sonnet, and Opus across speed and cost, see the impact of prompt caching on latency and spend, and instrument an agentic loop to understand where time actually goes.

---

## How to run

### Option 1 — GitHub Codespaces (no local install needed)

1. Go to the repo on GitHub and click the green **Code** button.
2. Select the **Codespaces** tab and click **Create codespace on main**.
3. Wait for the environment to load (takes about a minute).
4. Open `day2/02_inference-optimization/Inference_Optimization.ipynb`.
5. When prompted to select a kernel, choose **Python 3**.
6. In the API key cell, paste your key between the quotes.
7. Run cells with **Shift+Enter** or use **Run All** from the top menu.

---

### Option 2 — VS Code locally

1. Open VS Code and go to **File → Open Folder**, select this folder.
2. Install the **Python** and **Jupyter** extensions if prompted (search "Jupyter" in the Extensions panel).
3. Open `Inference_Optimization.ipynb` and select your Python environment as the kernel when prompted.
4. Open a terminal in VS Code (**Terminal → New Terminal**) and set your API key:
   ```bash
   export ANTHROPIC_API_KEY=your_key_here
   ```
5. Run cells with **Shift+Enter** or click **Run All** at the top of the notebook.

---

### Option 3 — Jupyter locally

1. Install Jupyter if needed: `pip install notebook`
2. Open a terminal, navigate to this folder, and set your API key:
   ```bash
   export ANTHROPIC_API_KEY=your_key_here
   cd path/to/day2/02_inference-optimization
   jupyter notebook Inference_Optimization.ipynb
   ```
3. In the browser tab that opens, run cells with **Shift+Enter** or use **Cell → Run All**.
