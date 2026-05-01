#!/usr/bin/env python
# coding: utf-8

# # Context Engineering 300: Is Context Rot Still Real?
# 
# [Chroma published research](https://research.trychroma.com/context-rot) evaluating many model providers (Anthropic, OpenAI, Google, Alibaba) and found that model performance degrades as input length grows — a phenomenon they called **"context rot."** Even on simple, controlled tasks, models that ace standard benchmarks showed surprising reliability gaps as context scaled.
# 
# These experimental results were originally published in Summer 2025 (a remarkably long time ago in the world of Applied AI). In this workbook you'll re-run some of the original context-rot experiments and then see how our latest models perform on these tasks.
# 
# **Format:** Self-paced, ~30 min hands-on. Run cells in order. Experiment sections have commented-out variations you can uncomment and try for yourself.
# 
# The goal at the end of this notebook is that you have an understanding of the original experiments, a point-of-view as to whether or not these experiments are still relevant, and the foundation to conduct some experiments of your own!
# 
# ---

# In[ ]:


get_ipython().run_line_magic('pip', 'install anthropic matplotlib seaborn pandas numpy python-Levenshtein tqdm -q')


# In[ ]:


import anthropic
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os
import time
import json
import random
import concurrent.futures
import Levenshtein
from pathlib import Path
from tqdm.notebook import tqdm
from IPython.display import display, Image

key = "" #INSERT API KEY
if not key:
  raise(ValueError("NO API KEY SET!"))

client = anthropic.Anthropic(api_key=key)

# ---- Pick your model ----
# Public model strings:
MODEL = "claude-sonnet-4-6"
# MODEL = "claude-opus-4-6"

JUDGE_MODEL = "claude-haiku-4-5-20251001"

# Style defaults
ANTHROPIC_ORANGE = "#E07A5F"
BASELINE_GRAY = "#8B8B8B"
plt.rcParams.update({"figure.dpi": 120, "figure.facecolor": "white"})

print(f"Using model: {MODEL}")
print(f"Judge model: {JUDGE_MODEL}")
print("Setup complete.")


# In[ ]:


# ============================================
# Core Helper Functions
# ============================================

def call_model(prompt, model=None, max_tokens=1000, system=None, thinking=None):
    """Single Anthropic API call. Returns response text."""
    model = model or MODEL
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    if thinking:
        kwargs["thinking"] = thinking
        kwargs["max_tokens"] = max(max_tokens, thinking.get("budget_tokens", 0) + max_tokens)
    response = client.messages.create(**kwargs)
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


def call_model_batch(items, model=None, max_tokens=1000, max_concurrent=10, system=None, thinking=None):
    """Concurrent batch API calls.

    items: list of prompts (strings) OR list of dicts with {"prompt": str, "max_tokens": int}
    Returns list of response texts in same order.
    """
    model = model or MODEL
    results = [None] * len(items)

    def _call(idx, item):
        if isinstance(item, dict):
            p = item["prompt"]
            mt = item.get("max_tokens", max_tokens)
        else:
            p = item
            mt = max_tokens
        return idx, call_model(p, model=model, max_tokens=mt, system=system, thinking=thinking)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = [executor.submit(_call, i, item) for i, item in enumerate(items)]
        for f in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="API calls"):
            idx, text = f.result()
            results[idx] = text
    return results


def llm_judge(question, correct_answer, model_output, model=None):
    """Use Claude as judge. Returns True/False."""
    model = model or JUDGE_MODEL
    judge_prompt = f"""Given this question and the CORRECT answer, determine whether the response is correct (meaning it factually aligns with the correct answer).
You must only respond with "true" or "false".
If the response is partially incorrect, such as a typo, respond with "false".
If the response contains additional supporting information while still maintaining the correct answer, respond with "true".

Question: {question}

CORRECT answer: {correct_answer}

Response to judge: {model_output}

Instructions: Respond with only "true" or "false"."""
    result = call_model(judge_prompt, model=model, max_tokens=10)
    return result.strip().lower() == "true"


def count_tokens(text, model=None):
    """Count tokens using Anthropic's token counting API."""
    model = model or MODEL
    response = client.messages.count_tokens(
        model=model,
        messages=[{"role": "user", "content": text}],
    )
    return response.input_tokens


print("Helper functions defined: call_model, call_model_batch, llm_judge, count_tokens")


# ---
# 
# ## Part 1: Repeated Words Experiment
# 
# **Task:** The model must reproduce a string of repeated words *exactly*. One word is modified (e.g., "apple" becomes "apples"), and the model must faithfully replicate everything — including the modified word in the correct position.
# 
# **Measures:**
# - **Levenshtein score** — how close is the output to the gold standard? (1.0 = perfect)
# - **Modified word present** — did the model include the different word at all?
# - **Position accuracy** — is the modified word in the right spot?
# 
# **Why it matters:** This is a pure faithfulness test. No reasoning required — just accurate reproduction as context grows.

# In[ ]:


# ============================================
# Load Chroma Reference Results (GPT-4.1)
# ============================================
# Chroma tested 18 models across providers. We have their GPT-4.1 results
# as one reference point from the broader study.

RESULTS_DIR = Path("chroma-experiments/results")

baseline_niah_path = RESULTS_DIR / "gpt_4_1_niah_evaluated.csv"
if baseline_niah_path.exists():
    baseline_niah_df = pd.read_csv(baseline_niah_path)
    baseline_niah_df["correct"] = baseline_niah_df["llm_judge_output"].apply(
        lambda x: 1 if str(x).lower() == "true" else 0
    )
    overall_niah_acc = baseline_niah_df["correct"].mean()
    print(f"GPT-4.1 NIAH results loaded (from Chroma study): {len(baseline_niah_df)} samples, {overall_niah_acc:.1%} accuracy")
    print(f"  Input lengths: {sorted(baseline_niah_df['approximate_input_length'].unique())}")
    print(f"  Needle depths: {sorted(baseline_niah_df['needle_depth'].unique())}")
else:
    print("No GPT-4.1 reference results found — we'll generate fresh results only.")
    baseline_niah_df = None

print()
print("Note: Chroma's repeated-words CSVs aren't included,")
print("so we'll generate all data fresh for that experiment.")


# In[ ]:


# ============================================
# Generate Repeated Words Data
# ============================================

COMMON_WORD = "apple"
MODIFIED_WORD = "apples"

def create_repeated_words_data(common_word, modified_word, num_words_list=None):
    """Generate repeated words prompts.

    For each word count, creates variations with the modified word at different positions.
    Returns a DataFrame with columns: id, prompt, gold, token_count, num_words, index
    """
    if num_words_list is None:
        num_words_list = [25, 50, 100, 250, 500, 1000, 2500]

    rows = []
    for wi, num_words in enumerate(num_words_list, 1):
        print(f"  Generating {num_words}-word variations ({wi}/{len(num_words_list)})...", end=" ")
        # Sample positions: all positions for small inputs, ~100 evenly spaced for large
        if num_words < 100:
            indices = list(range(num_words))
        else:
            step = max(1, num_words // 100)
            indices = list(range(0, num_words, step))
            if indices[-1] != num_words - 1:
                indices.append(num_words - 1)

        for idx in indices:
            gold = " ".join(
                modified_word if j == idx else common_word
                for j in range(num_words)
            )
            prompt = f"Simply replicate the following text, output the exact same text: {gold}"
            token_count = count_tokens(prompt)
            max_output_tokens = token_count * 2

            rows.append({
                "id": f"{num_words}_{idx}",
                "prompt": prompt,
                "gold": gold,
                "token_count": token_count,
                "max_output_tokens": max_output_tokens,
                "num_words": num_words,
                "index": idx,
            })
        print(f"{len(indices)} variations")

    return pd.DataFrame(rows)


rw_df = create_repeated_words_data(COMMON_WORD, MODIFIED_WORD)
print(f"\nGenerated {len(rw_df)} prompts across {rw_df['num_words'].nunique()} word counts")
print(f"Word counts: {sorted(rw_df['num_words'].unique())}")
print(f"Token range: {rw_df['token_count'].min()} - {rw_df['token_count'].max()}")
print()
print("Sample prompt (25 words, modified at position 3):")
sample = rw_df[rw_df["id"] == "25_3"].iloc[0]
print(f"  '{sample['prompt'][:120]}...'")


# In[ ]:


# ============================================
# Run Repeated Words on Claude Sonnet 4.5
# ============================================
# This calls the API — expect ~1-2 min for the full grid.

items = [
    {"prompt": row["prompt"], "max_tokens": row["max_output_tokens"]}
    for _, row in rw_df.iterrows()
]

print(f"Running {len(items)} prompts on {MODEL}...")
rw_outputs = call_model_batch(items, model=MODEL, max_concurrent=15)
rw_df["output"] = rw_outputs
print(f"Done! Got {sum(1 for o in rw_outputs if o)} responses.")


# In[ ]:


# ============================================
# Evaluate Repeated Words Results
# ============================================

def normalized_levenshtein_score(gold, pred):
    if not gold or not pred:
        return 0.0
    distance = Levenshtein.distance(gold, pred)
    max_len = max(len(gold), len(pred))
    return 1 - (distance / max_len)


def check_modified_word_present(row, modified_word):
    if pd.isna(row["output"]):
        return False
    # The modified word should appear with a space boundary
    if row["index"] == row["num_words"] - 1:
        marker = " " + modified_word
    else:
        marker = modified_word + " "
    return marker in row["output"]


def check_correct_position(row, modified_word):
    if not row["modified_word_present"] or pd.isna(row["output"]):
        return False
    try:
        if row["index"] == row["num_words"] - 1:
            marker = " " + modified_word
        else:
            marker = modified_word + " "
        return row["gold"].index(marker) == row["output"].index(marker)
    except ValueError:
        return False


# Compute metrics
rw_df["levenshtein_score"] = rw_df.apply(
    lambda r: normalized_levenshtein_score(r["gold"], r["output"]), axis=1
)
rw_df["modified_word_present"] = rw_df.apply(
    lambda r: check_modified_word_present(r, MODIFIED_WORD), axis=1
)
rw_df["correct_position"] = rw_df.apply(
    lambda r: check_correct_position(r, MODIFIED_WORD), axis=1
)
rw_df["delta"] = rw_df.apply(
    lambda r: len(r["gold"].split()) - len(str(r["output"]).split()) if pd.notna(r["output"]) else r["num_words"],
    axis=1,
)

# Summary by word count
summary = rw_df.groupby("num_words").agg(
    levenshtein=pd.NamedAgg("levenshtein_score", "mean"),
    modified_present=pd.NamedAgg("modified_word_present", "mean"),
    position_acc=pd.NamedAgg("correct_position", "mean"),
    count=pd.NamedAgg("id", "count"),
).round(3)

print("Results by word count:")
display(summary)
print(f"\nOverall Levenshtein: {rw_df['levenshtein_score'].mean():.4f}")
print(f"Overall modified word present: {rw_df['modified_word_present'].mean():.1%}")
print(f"Overall position accuracy: {rw_df['correct_position'].mean():.1%}")


# In[ ]:


# ============================================
# Visualize: Levenshtein Score vs Input Tokens
# ============================================

fig, ax = plt.subplots(figsize=(10, 5))

# Bin by token count and plot average Levenshtein score
num_bins = 10
min_tok = max(rw_df["token_count"].min(), 1)
bins = np.logspace(np.log10(min_tok), np.log10(rw_df["token_count"].max()), num_bins + 1)
rw_df["token_bin"] = pd.cut(rw_df["token_count"], bins=bins, include_lowest=True, labels=False)

bin_centers, avg_scores = [], []
for b in range(num_bins):
    subset = rw_df[rw_df["token_bin"] == b]
    if not subset.empty:
        avg_scores.append(subset["levenshtein_score"].mean())
        bin_centers.append(np.sqrt(bins[b] * bins[b + 1]))

ax.plot(bin_centers, avg_scores, marker="o", color=ANTHROPIC_ORANGE, linewidth=2, label="Claude Sonnet 4.5")
ax.set_xscale("log")
ax.set_xlabel("Input Length (tokens)")
ax.set_ylabel("Avg Normalized Levenshtein Score")
ax.set_title(f'Repeated "{COMMON_WORD}", one "{MODIFIED_WORD}" — Faithfulness vs Context Length')
ax.set_ylim(0, 1.05)
ax.grid(True, alpha=0.3)
ax.legend()
plt.tight_layout()
plt.show()

# Per-word-count breakdown
fig, axes = plt.subplots(1, 3, figsize=(15, 4))
for ax_i, (metric, label) in enumerate([
    ("levenshtein_score", "Levenshtein Score"),
    ("modified_word_present", "Modified Word Present"),
    ("correct_position", "Correct Position"),
]):
    means = rw_df.groupby("num_words")[metric].mean()
    axes[ax_i].bar(range(len(means)), means.values, color=ANTHROPIC_ORANGE, alpha=0.8)
    axes[ax_i].set_xticks(range(len(means)))
    axes[ax_i].set_xticklabels(means.index, rotation=45)
    axes[ax_i].set_xlabel("Word Count")
    axes[ax_i].set_ylabel(label)
    axes[ax_i].set_ylim(0, 1.05)
    axes[ax_i].set_title(label)
plt.suptitle(f"Claude Sonnet 4.5 — Repeated Words Metrics", fontsize=13)
plt.tight_layout()
plt.show()


# **Feel free to try these variations** — uncomment any block, re-run cells 7–9:
# 
# ```python
# # --- TRY: Enable extended thinking ---
# # Does thinking help with faithful reproduction?
# # Add to the call_model_batch call:
# # rw_outputs = call_model_batch(items, model=MODEL, max_concurrent=10,
# #                               thinking={"type": "enabled", "budget_tokens": 2048})
# 
# # --- TRY: Switch to Opus ---
# # MODEL = "claude-opus-4–5-20251101"
# 
# # --- TRY: Different word pairs ---
# # COMMON_WORD = "the"
# # MODIFIED_WORD = "teh"
# # rw_df = create_repeated_words_data(COMMON_WORD, MODIFIED_WORD)
# ```

# ---
# 
# ## Part 2: Needle In A Haystack (NIAH) Extension
# 
# The standard NIAH test hides a fact ("needle") inside a long document ("haystack") and asks the model to retrieve it. Chroma's experiment requires a slightly finer understanding:
# 
# - **Semantic matching** — the model must understand the needle, not just pattern-match
# - **Distractors** — semantically similar false needles that could fool the model
# 
# Across the 18 models Chroma tested, NIAH performance varied widely — even models that scored well on standard benchmarks showed failures at specific depths and lengths. Here's GPT-4.1's heatmap as one reference:

# In[ ]:


# Show GPT-4.1 heatmap from Chroma's multi-model study
heatmap_path = RESULTS_DIR / "gpt_4_1_heatmap.png"
if heatmap_path.exists():
    print("GPT-4.1 NIAH Heatmap (one of 18 models from Chroma's study):")
    display(Image(filename=str(heatmap_path), width=700))
else:
    print("GPT-4.1 heatmap not found. We'll create our own from scratch.")


# In[ ]:


# ============================================
# Haystack Data Setup
# ============================================

PG_ESSAYS_DIR = Path("chroma-experiments/data/PaulGrahamEssays")
USE_SYNTHETIC = not PG_ESSAYS_DIR.exists()

if USE_SYNTHETIC:
    print("Paul Graham essays not found — using synthetic haystack text.")
    print("(For the full experience, download PG essays from:")
    print(" https://drive.google.com/drive/folders/14uHYF65yu7cNGANungZX1NRboqwHHuVB")
    print(f" and place .txt files in {PG_ESSAYS_DIR}). Then re-run this cell.")
    print()

TOPIC_PARAGRAPHS = [
    ("The history of computing is filled with unexpected turns. Early pioneers like Ada Lovelace "
     "imagined machines that could compose music and process symbols, long before transistors existed. "
     "The gap between vision and implementation has always been central to progress in technology."),
    ("Scientific methodology evolved gradually over centuries. From the empirical observations of "
     "Aristotle to the controlled experiments of the Enlightenment, each era contributed tools for "
     "understanding the natural world. The key insight was that nature could be interrogated systematically."),
    ("Philosophy has long debated the nature of knowledge itself. Epistemologists distinguish between "
     "knowing that something is true and knowing how to do something. This distinction matters in "
     "artificial intelligence, where declarative and procedural knowledge serve different purposes."),
    ("Urban planning in the twentieth century underwent dramatic shifts. The modernist vision of "
     "separated zones for living, working, and recreation gave way to mixed-use developments that "
     "emphasized walkability and community interaction over automotive convenience."),
    ("The economics of information goods differ fundamentally from physical products. Digital content "
     "has near-zero marginal cost of reproduction, which undermines traditional pricing models based "
     "on scarcity. This creates both opportunities and challenges for creators and platforms."),
    ("Ecological systems demonstrate remarkable resilience through redundancy and diversity. When one "
     "species declines, others often fill its niche, maintaining ecosystem function. This principle "
     "has inspired approaches to designing robust engineering systems and organizations."),
    ("The development of writing systems transformed human civilization. From cuneiform to alphabets, "
     "each innovation in recording language expanded the scope of collective memory and enabled new "
     "forms of social organization, law, and commerce across distances and generations."),
    ("Mathematical proof provides a unique form of certainty unavailable in empirical sciences. "
     "Once proven, a theorem holds universally and permanently. Yet the process of discovering proofs "
     "often involves intuition, guessing, and aesthetic judgment before rigorous formalization."),
    ("The psychology of decision-making reveals systematic biases that affect even experts. Anchoring, "
     "availability heuristics, and confirmation bias shape judgments in predictable ways. Understanding "
     "these patterns is essential for designing better institutions and decision processes."),
    ("Agricultural innovation has repeatedly reshaped societies. The Green Revolution increased yields "
     "dramatically through improved crop varieties and fertilizers, but also raised questions about "
     "sustainability, biodiversity loss, and the concentration of food production systems."),
]


def generate_synthetic_haystack(target_tokens):
    """Generate essay-like filler text, trimmed to approximate target token count.

    Uses ~4 chars/token heuristic for building, then one API call to verify.
    """
    target_chars = target_tokens * 4  # rough estimate
    text = ""
    i = 0
    while len(text) < target_chars:
        text += TOPIC_PARAGRAPHS[i % len(TOPIC_PARAGRAPHS)] + "\n\n"
        i += 1

    # Trim by characters — slightly overshoot then truncate at sentence boundary
    if len(text) > target_chars:
        # Find the last period before our target
        cut = text[:target_chars].rfind(". ")
        if cut > 0:
            text = text[:cut + 1]
        else:
            text = text[:target_chars]
    return text


def load_haystack_texts():
    """Load PG essays if available."""
    if not USE_SYNTHETIC:
        import glob
        txt_files = glob.glob(str(PG_ESSAYS_DIR / "*.txt"))
        texts = []
        for fp in txt_files:
            with open(fp, "r", encoding="utf-8") as f:
                texts.append(f.read().strip())
        print(f"Loaded {len(texts)} PG essays")
        return texts
    return None


haystack_texts = load_haystack_texts()
print(f"Haystack source: {'Paul Graham essays' if haystack_texts else 'Synthetic text'}")


# In[ ]:


# ============================================
# Build NIAH Prompts
# ============================================

NEEDLE = ("It sometimes surprises people when I tell them I write every week. "
          "I was also surprised when my friend from my freshman year History course "
          "was doing the same thing, but looking back, I only wish I started earlier.")
QUESTION = "What was the best writing advice I got from my college classmate?"

# Reduced grid for speed — same methodology, fewer cells
INPUT_LENGTHS = [500, 1_000, 5_000, 10_000, 50_000]
DEPTHS = [0, 25, 50, 75, 100]


def build_haystack(target_tokens, texts=None):
    """Build haystack of approximately target_tokens length.

    Uses character estimates (~4 chars/token) to avoid tight-loop API calls.
    """
    target_chars = target_tokens * 4

    if texts:
        haystack = ""
        idx = 0
        while len(haystack) < target_chars:
            next_text = texts[idx % len(texts)]
            haystack += next_text + "\n\n"
            idx += 1
        # Trim at sentence boundary
        if len(haystack) > target_chars:
            cut = haystack[:target_chars].rfind(". ")
            if cut > 0:
                haystack = haystack[:cut + 1]
            else:
                haystack = haystack[:target_chars]
        return haystack
    else:
        return generate_synthetic_haystack(target_tokens)


def insert_needle_at_depth(haystack, needle, depth_percent):
    """Insert needle at a given depth percentage into the haystack.

    Works at character level, aligning to sentence boundaries.
    """
    if depth_percent >= 100:
        return haystack + " " + needle
    if depth_percent <= 0:
        return needle + " " + haystack

    # Find insertion point as percentage of text length
    point = int(len(haystack) * (depth_percent / 100))

    # Align to nearest sentence boundary (look backward for ". ")
    boundary = haystack.rfind(". ", 0, point)
    if boundary > 0:
        point = boundary + 2  # after the ". "

    return haystack[:point] + needle + " " + haystack[point:]


def create_niah_prompt(haystack_with_needle, question):
    """Wrap haystack+needle in the NIAH prompt template."""
    return f"""You are a helpful AI bot that answers questions for a user. Keep your response short and direct

<document_content>
{haystack_with_needle}
</document_content>

Here is the user question:
<question>
{question}
</question>

Don't give information outside the document or repeat your findings.
Here is the most relevant information in the documents:"""


# Build the prompt grid
overhead_tokens = count_tokens(create_niah_prompt("", QUESTION))
needle_tokens = count_tokens(NEEDLE)

niah_prompts = []
for li, length in enumerate(INPUT_LENGTHS, 1):
    available = length - overhead_tokens - needle_tokens
    if available <= 100:
        print(f"Skipping length {length} — not enough room for haystack")
        continue

    print(f"  Building {length:,}-token haystacks ({li}/{len(INPUT_LENGTHS)})...")
    base_haystack = build_haystack(available, haystack_texts)

    for depth in DEPTHS:
        haystack_with_needle = insert_needle_at_depth(base_haystack, NEEDLE, depth)
        prompt = create_niah_prompt(haystack_with_needle, QUESTION)
        actual_tokens = count_tokens(prompt)

        niah_prompts.append({
            "prompt": prompt,
            "token_count": actual_tokens,
            "approximate_input_length": length,
            "needle_depth": depth,
            "question": QUESTION,
            "answer": NEEDLE,
        })

niah_df = pd.DataFrame(niah_prompts)
print(f"\nGenerated {len(niah_df)} NIAH prompts")
print(f"  Lengths: {sorted(niah_df['approximate_input_length'].unique())}")
print(f"  Depths: {sorted(niah_df['needle_depth'].unique())}")
print(f"  Token range: {niah_df['token_count'].min()} - {niah_df['token_count'].max()}")


# In[ ]:


# ============================================
# Run NIAH on Claude Sonnet 4.5
# ============================================

print(f"Running {len(niah_df)} NIAH prompts on {MODEL}...")
print("(Largest prompt is ~50K tokens — this may take a couple minutes)")

niah_outputs = call_model_batch(
    niah_df["prompt"].tolist(), model=MODEL, max_tokens=200, max_concurrent=10
)
niah_df["output"] = niah_outputs
print(f"Done! Got {sum(1 for o in niah_outputs if o)} responses.")


# In[ ]:


# ============================================
# Evaluate NIAH with Claude Judge
# ============================================

print(f"Judging {len(niah_df)} responses with {JUDGE_MODEL}...")

judge_results = []
for _, row in tqdm(niah_df.iterrows(), total=len(niah_df), desc="Judging"):
    result = llm_judge(row["question"], row["answer"], row["output"])
    judge_results.append(result)

niah_df["correct"] = judge_results
niah_df["accuracy"] = niah_df["correct"].astype(int)

# Summary
overall_acc = niah_df["accuracy"].mean()
print(f"\nOverall NIAH accuracy: {overall_acc:.1%}")
print("\nAccuracy by input length:")
print(niah_df.groupby("approximate_input_length")["accuracy"].mean().to_string())
print("\nAccuracy by needle depth:")
print(niah_df.groupby("needle_depth")["accuracy"].mean().to_string())


# In[ ]:


# ============================================
# NIAH Heatmap + Comparison
# ============================================

from matplotlib.colors import ListedColormap

def plot_niah_heatmap(df, title, ax=None):
    """Plot NIAH accuracy heatmap."""
    lengths = sorted(df["approximate_input_length"].unique())
    depths = sorted(df["needle_depth"].unique())

    pivot = df.groupby(["needle_depth", "approximate_input_length"])["accuracy"].mean()
    pivot = pivot.reset_index().pivot(index="needle_depth", columns="approximate_input_length", values="accuracy")

    heatmap_data = pd.DataFrame(index=depths, columns=lengths, dtype=float)
    for d in depths:
        for l in lengths:
            if d in pivot.index and l in pivot.columns:
                val = pivot.loc[d, l]
                if pd.notna(val):
                    heatmap_data.loc[d, l] = val

    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 5))

    cmap = ListedColormap(["white", ANTHROPIC_ORANGE])
    cmap.set_bad(color="lightgrey")

    im = ax.imshow(heatmap_data.values.astype(float), cmap=cmap, aspect="auto",
                   vmin=0, vmax=1, origin="lower")

    length_labels = [f"{l//1000}K" if l >= 1000 else str(l) for l in lengths]
    ax.set_xticks(range(len(lengths)))
    ax.set_xticklabels(length_labels)
    ax.set_yticks(range(len(depths)))
    ax.set_yticklabels([f"{int(d)}%" for d in depths])
    ax.set_xlabel("Input Length (tokens)")
    ax.set_ylabel("Needle Depth")
    ax.set_title(title)
    return ax


# Plot comparison
fig, axes = plt.subplots(1, 2, figsize=(16, 5))

# GPT-4.1 from Chroma study (if available)
if baseline_niah_df is not None:
    matching_baseline = baseline_niah_df[
        baseline_niah_df["approximate_input_length"].isin(INPUT_LENGTHS) &
        baseline_niah_df["needle_depth"].isin(DEPTHS)
    ].copy()
    matching_baseline["accuracy"] = matching_baseline["correct"]
    if len(matching_baseline) > 0:
        plot_niah_heatmap(matching_baseline, "GPT-4.1 (from Chroma study)", ax=axes[0])
    else:
        axes[0].text(0.5, 0.5, "No matching data at these depths/lengths",
                    ha="center", va="center", transform=axes[0].transAxes)
        axes[0].set_title("GPT-4.1 (no matching data)")
else:
    axes[0].text(0.5, 0.5, "Reference data not available",
                ha="center", va="center", transform=axes[0].transAxes)
    axes[0].set_title("GPT-4.1 (not loaded)")

# Claude Sonnet 4.5
plot_niah_heatmap(niah_df, "Claude Sonnet 4.5", ax=axes[1])

plt.suptitle("NIAH Performance Comparison", fontsize=14)
plt.tight_layout()
plt.show()

# Print comparison
claude_acc = niah_df["accuracy"].mean()
print(f"\nClaude Sonnet 4.5 overall: {claude_acc:.1%}")
if baseline_niah_df is not None:
    baseline_acc = baseline_niah_df["correct"].mean()
    print(f"GPT-4.1 overall (from Chroma study, full grid): {baseline_acc:.1%}")


# ### Try Variations
# 
# (Optional) Uncomment any block below to experiment, then re-run cells 14–16:
# 
# ```python
# # --- EXPERIMENT: Add distractors ---
# # Semantically similar false needles that could fool the model:
# #
# # DISTRACTORS = [
# #     "The best writing tip I received from my college professor was to write everyday.",
# #     "The worst writing advice I got from my college classmate was to write each essay in five different styles.",
# #     "The best writing advice I got from my classmate was to write each essay in three different styles.",
# # ]
# #
# # To use: modify the build loop to insert distractors:
# # for depth in DEPTHS:
# #     # Insert distractors randomly into the haystack
# #     sentences = base_haystack.split('. ')
# #     for d in DISTRACTORS:
# #         pos = random.randint(1, len(sentences) - 1)
# #         sentences.insert(pos, d)
# #     haystack_with_distractors = '. '.join(sentences)
# #     haystack_with_needle = insert_needle_at_depth(haystack_with_distractors, NEEDLE, depth)
# 
# # --- EXPERIMENT: Shuffle haystack ---
# # Destroy document structure by randomizing sentence order:
# # SHUFFLE_SENTENCES = True
# # base_haystack_sentences = base_haystack.split('. ')
# # random.shuffle(base_haystack_sentences)
# # base_haystack = '. '.join(base_haystack_sentences)
# 
# # --- EXPERIMENT: Custom needle ---
# # Try your own needle/question pair:
# # NEEDLE = "The secret ingredient in my grandmother's famous pasta sauce is a tablespoon of cinnamon."
# # QUESTION = "What is the secret ingredient in my grandmother's pasta sauce?"
# ```

# ---
# 
# ## Part 3: Design Your Own Experiment
# 
# The above experiments are a slightly contrived. These are useful for understanding and demonstrating the different performance characteristics of language models, but in practice might not replicate the kinds of issues customers deal with on a day to day basis.
# 
# As discussed in the presentation, a core part of the Applied AI role is understanding the state of LLM performance at any given time. The best way to do that is to run experiments, surfacing customer data, and build frontier agents that stress the current capabilities of LLMs (ex/ Eugene Yan's recent experiments [here](https://anthropic.slack.com/archives/C0A8NT9ACR4/p1771383797300529). Below are a handful of seed questions that, many inspired from customer conversations, that you could use to build out your own context-engineering experiments. You are encouraged to start by writing out a spec / experimental brief for the questions you'd like to test, and then use claude code to help you build the full experiment.
# ### Seed Ideas
# 
# **Prompt-level:**
# - Does `<important>` XML tagging around the needle improve NIAH?
# - Does placing instructions at beginning vs. end of context matter?
# - Does "think step by step before answering" improve retrieval?
# - How does system prompt vs. user message placement affect results?
# 
# **Thinking / Reasoning:**
# - Thinking budget sweep: 0 vs 1K vs 5K vs 10K tokens — does more thinking help?
# - Self-verification: "double-check your answer against the source"
# 
# **Architecture-level:**
# - Tool-use retrieval: give the model a search tool over its own context
# - Summarize-then-answer: first summarize each section, then answer from summaries
# - Context chunking: break into chunks, retrieve relevant ones, then answer
# - Multi-turn vs single-turn: does conversational chunking help?
# 
# **Model comparison:**
# - Haiku vs Sonnet vs Opus on same tasks
# - Same model with different temperatures
# - Thinking enabled vs disabled across the board

# In[ ]:


# ============================================
# YOUR EXPERIMENT — Scaffold
# ============================================
# Copy this cell, fill it in, and run it.

EXPERIMENT_NAME = "..."
HYPOTHESIS = "..."
INDEPENDENT_VARIABLE = "..."


def generate_conditions():
    """Return dict of {condition_name: list_of_prompts}.

    Each prompt should be a string (the full prompt to send to the model).
    For experiments needing evaluation, also track expected answers separately.
    """
    conditions = {}
    # Example:
    # conditions["control"] = ["prompt1", "prompt2", ...]
    # conditions["treatment"] = ["prompt1_modified", "prompt2_modified", ...]
    return conditions


def evaluate_condition(prompts, outputs):
    """Score a list of model outputs against prompts. Return a metric (0-1)."""
    # Example: use llm_judge, string matching, Levenshtein, etc.
    return 0.0


# --- Run it ---
# conditions = generate_conditions()
# all_results = {}
# for name, prompts in conditions.items():
#     outputs = call_model_batch(prompts, MODEL)
#     all_results[name] = evaluate_condition(prompts, outputs)
#     print(f"{name}: {all_results[name]:.2%}")

# --- Plot it ---
# plt.bar(all_results.keys(), all_results.values(), color=ANTHROPIC_ORANGE)
# plt.ylabel("Accuracy")
# plt.title(EXPERIMENT_NAME)
# plt.ylim(0, 1.05)
# plt.show()

print("Scaffold ready — fill in generate_conditions() and evaluate_condition(), then uncomment the run block.")


# In[ ]:


# ============================================
# Worked Example: XML Tagging for NIAH
# ============================================
# Hypothesis: Wrapping the needle in <key_information> tags improves
# NIAH accuracy at longer context lengths.

EXPERIMENT_NAME = "XML Tagging Improves NIAH Retrieval"
TEST_LENGTHS = [5_000, 10_000, 50_000]
TEST_DEPTH = 50  # middle of the document

# Build control (no tags) and treatment (XML tags) prompts
control_prompts = []
treatment_prompts = []

for length in TEST_LENGTHS:
    available = length - overhead_tokens - needle_tokens
    if available <= 100:
        continue

    base = build_haystack(available, haystack_texts)

    # Control: plain needle
    control_haystack = insert_needle_at_depth(base, NEEDLE, TEST_DEPTH)
    control_prompts.append(create_niah_prompt(control_haystack, QUESTION))

    # Treatment: XML-tagged needle
    tagged_needle = f"<key_information>{NEEDLE}</key_information>"
    treatment_haystack = insert_needle_at_depth(base, tagged_needle, TEST_DEPTH)
    treatment_prompts.append(create_niah_prompt(treatment_haystack, QUESTION))

print(f"Control prompts: {len(control_prompts)}")
print(f"Treatment prompts: {len(treatment_prompts)}")

# Run both conditions
print("\nRunning control (no tags)...")
control_outputs = call_model_batch(control_prompts, model=MODEL, max_tokens=200)

print("Running treatment (XML tags)...")
treatment_outputs = call_model_batch(treatment_prompts, model=MODEL, max_tokens=200)

# Judge
print("\nJudging results...")
control_scores = [llm_judge(QUESTION, NEEDLE, out) for out in control_outputs]
treatment_scores = [llm_judge(QUESTION, NEEDLE, out) for out in treatment_outputs]

control_acc = sum(control_scores) / len(control_scores) if control_scores else 0
treatment_acc = sum(treatment_scores) / len(treatment_scores) if treatment_scores else 0

print(f"\nControl (no tags):  {control_acc:.0%}")
print(f"Treatment (XML):    {treatment_acc:.0%}")

# Per-length breakdown
print("\nPer-length breakdown:")
for i, length in enumerate(TEST_LENGTHS[:len(control_scores)]):
    label = f"{length//1000}K" if length >= 1000 else str(length)
    c = "correct" if control_scores[i] else "wrong"
    t = "correct" if treatment_scores[i] else "wrong"
    print(f"  {label}: control={c}, XML={t}")

# Plot
fig, ax = plt.subplots(figsize=(6, 4))
x = np.arange(2)
bars = ax.bar(x, [control_acc, treatment_acc], color=[BASELINE_GRAY, ANTHROPIC_ORANGE], width=0.5)
ax.set_xticks(x)
ax.set_xticklabels(["Control\n(no tags)", "Treatment\n(<key_information>)"])
ax.set_ylabel("Accuracy")
ax.set_ylim(0, 1.15)
ax.set_title(EXPERIMENT_NAME)
for bar in bars:
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.03,
            f"{bar.get_height():.0%}", ha="center", fontsize=12)
plt.tight_layout()
plt.show()


# ### Build Your Own!
# 
# Ideate and build your own experiment, then reflect on what you found.
# 
# There are no wrong experiments here — the goal is to build intuition for how language models work and fail in many different types of problem solving.
# 
# Take a few minutes after running your experiment to reflect: What did you expect to happen? What actually happened? What would you test next?
# 
# **Before we wrap up:** We'd love to hear from a few people — what experiment did you run, and what surprised you most? No need to prepare anything formal — just share one thing.

# ---
# 
# ## (Bonus / Optional) Part 4: LongMemEval
# 
# LongMemEval tests whether models can answer questions from very long conversational histories (~113K tokens). Chroma tested GPT-4.1 in two modes:
# 
# - **Focused**: Only the relevant conversation turns are included
# - **Full**: The entire conversation history is included
# 
# This section requires downloading the LongMemEval dataset. If you don't have it, you can still view the GPT-4.1 baselines.
# 
# **Dataset:** [LongMemEval on GitHub](https://github.com/xiaowu0162/LongMemEval)

# In[ ]:


# ============================================
# LongMemEval — GPT-4.1 Baselines
# ============================================

focused_eval_path = RESULTS_DIR / "gpt_4_1_longmemeval_focused_evaluated.csv"
full_eval_path = RESULTS_DIR / "gpt_4_1_longmemeval_full_evaluated.csv"

has_baselines = focused_eval_path.exists() and full_eval_path.exists()

if has_baselines:
    focused_df = pd.read_csv(focused_eval_path)
    full_df = pd.read_csv(full_eval_path)

    focused_acc = focused_df["llm_judge_output"].apply(lambda x: str(x).lower() == "true").mean()
    full_acc = full_df["llm_judge_output"].apply(lambda x: str(x).lower() == "true").mean()

    print(f"GPT-4.1 LongMemEval Results:")
    print(f"  Focused context: {focused_acc:.1%} ({len(focused_df)} questions)")
    print(f"  Full context:    {full_acc:.1%} ({len(full_df)} questions)")
    print(f"  Delta:           {focused_acc - full_acc:+.1%}")

    # Plot baseline
    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(["Focused", "Full"], [focused_acc, full_acc],
                  color=["#EB4026", "#3A76E5"])
    ax.set_ylim(0, 1)
    ax.set_ylabel("Accuracy")
    ax.set_title("GPT-4.1 — LongMemEval Performance")
    for bar in bars:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                f"{bar.get_height():.1%}", ha="center", fontsize=11)
    plt.tight_layout()
    plt.show()
else:
    print("GPT-4.1 LongMemEval baselines not found.")
    print("Expected files:")
    print(f"  {focused_eval_path}")
    print(f"  {full_eval_path}")


# In[ ]:


# ============================================
# LongMemEval — Run on Claude (if you have the data)
# ============================================
# To run this section:
# 1. Download LongMemEval: https://github.com/xiaowu0162/LongMemEval
# 2. Prepare a CSV with columns: question, answer, prompt (focused), prompt_full (full context)
# 3. Uncomment and run below

# LONGMEMEVAL_PATH = "path/to/longmemeval_prepared.csv"
#
# if os.path.exists(LONGMEMEVAL_PATH):
#     lme_df = pd.read_csv(LONGMEMEVAL_PATH)
#     # Take a subset for speed
#     lme_subset = lme_df.sample(n=min(20, len(lme_df)), random_state=42)
#
#     print(f"Running {len(lme_subset)} LongMemEval questions (focused)...")
#     focused_outputs = call_model_batch(
#         lme_subset["prompt"].tolist(), model=MODEL, max_tokens=500
#     )
#
#     print(f"Running {len(lme_subset)} LongMemEval questions (full context)...")
#     full_outputs = call_model_batch(
#         lme_subset["prompt_full"].tolist(), model=MODEL, max_tokens=500
#     )
#
#     # Judge
#     focused_scores = [
#         llm_judge(q, a, o)
#         for q, a, o in zip(lme_subset["question"], lme_subset["answer"], focused_outputs)
#     ]
#     full_scores = [
#         llm_judge(q, a, o)
#         for q, a, o in zip(lme_subset["question"], lme_subset["answer"], full_outputs)
#     ]
#
#     claude_focused = sum(focused_scores) / len(focused_scores)
#     claude_full = sum(full_scores) / len(full_scores)
#     print(f"\nClaude Sonnet 4.5 LongMemEval:")
#     print(f"  Focused: {claude_focused:.1%}")
#     print(f"  Full:    {claude_full:.1%}")

print("LongMemEval section ready — uncomment the code above after downloading the dataset.")


# In[ ]:


# ============================================
# LongMemEval — Compare with GPT-4.1
# ============================================
# Uncomment after running the cell above

# if has_baselines and 'claude_focused' in dir():
#     fig, ax = plt.subplots(figsize=(8, 5))
#     x = np.arange(2)
#     width = 0.35
#
#     bars1 = ax.bar(x - width/2, [focused_acc, full_acc], width,
#                    label="GPT-4.1", color=BASELINE_GRAY)
#     bars2 = ax.bar(x + width/2, [claude_focused, claude_full], width,
#                    label="Claude Sonnet 4.5", color=ANTHROPIC_ORANGE)
#
#     ax.set_xticks(x)
#     ax.set_xticklabels(["Focused", "Full Context"])
#     ax.set_ylabel("Accuracy")
#     ax.set_ylim(0, 1)
#     ax.set_title("LongMemEval: GPT-4.1 vs Claude Sonnet 4.5")
#     ax.legend()
#
#     for bars in [bars1, bars2]:
#         for bar in bars:
#             ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
#                     f"{bar.get_height():.1%}", ha="center", fontsize=10)
#
#     plt.tight_layout()
#     plt.show()

print("Comparison chart ready — uncomment after running LongMemEval on Claude.")

