# check_project.py — project proposal check

`check_project.py` runs your embedding model on a **sample** of your corpus and tells you:

- the dimension and the maximum sequence length of your model;
- how your sample is distributed across languages;
- how many 256-token chunks your **full** corpus will produce;
- how long your laptop would take to compute all the embeddings;

and checks the corpus requirements of the project brief (Part 1, sections 2, 3 and 4).

You must copy its complete output at the end of your proposal (brief, section 5.2).

**Read this whole file before running the script.** If the sample does not have one of the two formats described in step 1, the script will not work.

---

## Step 0. Environment

Use the conda environment of the labs (`bdav`). You need `sentence-transformers` 5.6 or later, and `pandas` if you use format B:

```
conda activate bdav
pip install -U "sentence-transformers>=5.6" pandas
```

**Why 5.6, and not 5.4 as in labs 5 to 7?** Versions earlier than 5.6.0 have a security vulnerability (CVE-2026-68770, published in July 2026): the protection `trust_remote_code=False` can be bypassed when a model is loaded from a local folder, so a tampered model could execute code on your computer (https://advisories.gitlab.com/pypi/sentence-transformers/CVE-2026-68770/). We did not detect it when we prepared those labs; we learned about it afterwards. Check your version with `pip show sentence-transformers`. The script refuses to run with an older version.

The first time you run the script with a model, it downloads it from Hugging Face. Depending on the model, that is between about 0.5 and 2.5 GB: do it at home, not on the lab Wi-Fi.

## Step 1. Prepare the sample

### What the sample must be

- **Between 50 and 500 documents.** With fewer than 50, the script still runs, but its estimates are unreliable.
- **Chosen at random from your source**, not the first ones (the first ones are often atypical: the oldest, the shortest, the ones in one category).
- **With the languages in the same proportion as in your full corpus.** If your corpus will be 70 % Spanish and 30 % English, so should your sample be.
- **Each document as it will be in your corpus**: clean text, without menus or HTML, and split the way you plan to split it (for instance, one chapter per document if your source has books; brief, section 2.2).

### Format: choose ONE of these two, whichever is easier for you

**Format A — a folder per language, a `.txt` file per document.** No programming needed.

```
muestra/
├── es/
│   ├── doc001.txt
│   ├── doc002.txt
│   └── ...
└── en/
    ├── doc101.txt
    └── ...
```

- The name of each subfolder is the language code (`es`, `en`, `fr`, `gl`…). The script uses it as the language.
- Each `.txt` file contains the text of one document, in UTF-8. The file names do not matter.

**Format B — a single `.csv` or `.jsonl` file** with (at least) two columns, exactly with these names:

| Column | Content |
|---|---|
| `text` | The text of the document |
| `language` | Its language code (`es`, `en`…) |

Other columns are ignored. For example, a `muestra.csv`:

```
text,language
"El Real Madrid ganó la Copa de Europa de 1956...",es
"Liverpool Football Club is a professional football club...",en
```

If your corpus comes from Hugging Face or is in a pandas DataFrame, writing this file takes one or two lines. For example:

```python
# df is a DataFrame with your documents; adapt the names of YOUR columns
sample = df.sample(n=300, random_state=42)        # random sample
sample = sample.rename(columns={"article": "text", "lang": "language"})
sample[["text", "language"]].to_csv("muestra.csv", index=False)
```

## Step 2. Find out how your model encodes queries and passages

Look it up in the **card of your model** on Hugging Face (remember lab 5, section 1.3). Some models need a text in front of each query and/or each passage; others need nothing. You pass them to the script with `--query-prefix` and `--passage-prefix`:

- Copy them **exactly**, including the final space if there is one, and in quotes.
- If your model needs nothing, do not pass these arguments.

## Step 3. Estimate the number of documents of your full corpus

You pass it with `--total-docs`. Use the number you will write in your proposal (brief, section 2.7). The script multiplies the average number of chunks per document of the sample by this number.

## Step 4. Run it

From the folder where you saved the script, in one line (it works the same on macOS, Linux and Windows):

```
python check_project.py --sample muestra --model YOUR_MODEL --total-docs 8000 --query-prefix "..." --passage-prefix "..."
```

- `--sample`: the folder (format A) or the `.csv` / `.jsonl` file (format B).
- `--model`: the Hugging Face name of your model, as it appears at the top of its card (e.g. `intfloat/multilingual-e5-base`).

To save the output to a file, add `> check_project.txt` at the end of the line. The script takes from a few seconds to a few minutes, depending on your laptop and your model.

## Reading the output

The output has five parts: **1. Model**, **2. Sample**, **3. Full corpus**, **4. Speed** and **5. Requirements**. In part 5, each requirement is marked `[OK]` or `[WARNING]`.

A `[WARNING]` does not stop the script: it is a check, not an exam. But it tells you that something does not meet the brief:

- **Dimension or `max_seq_length`**: the model does not meet the criteria of section 4.1. Choose another one.
- **Fewer than 2 languages, or a language below 20 %**: check your sample first (is it in the right proportion?) and then your corpus (section 3).
- **Fewer than 25,000 chunks or 1,000 documents**: your source is not enough (section 2.1). Look for more text, or another source.
- **Estimated time too long for you**: try a smaller model (section 4.3) before reducing the corpus below the minimum.

## Common errors

| Message | What to do |
|---|---|
| `... does not exist` | The path given to `--sample` is wrong. For format B, include the extension (`muestra.csv`, not `muestra`). Run the script from the folder that contains the sample, or give the full path. |
| `must have the columns 'text' and 'language'` | Format B: rename your columns exactly like that. |
| `has no subfolders` | Format A: the documents must be inside one subfolder per language, not directly in `muestra/`. |
| `needs trust_remote_code=True` | That model does not meet criterion 5 (section 4.1). Choose another one. |
| `Could not load the model` | Check the name of the model (copy it from Hugging Face) and your internet connection. |
| `sentence-transformers ... is too old` | `pip install -U "sentence-transformers>=5.6"` |
