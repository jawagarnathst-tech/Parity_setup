# 📋 SBC PDF Automation Platform — Instructions

Welcome! This guide will help you understand how to use this platform step by step. No technical knowledge required.

---

## 🛠️ First Time Setup (Do This Once Only)

Follow these steps the **very first time** you use this project on a new computer.

### Step 1 — Open a Terminal in the Project Folder
Open **PowerShell** or **Command Prompt** and navigate to the project:
```bash
cd c:\SBC
```

### Step 2 — Create a Virtual Environment
A virtual environment keeps all the project's libraries isolated and clean:
```bash
python -m venv venv
```
You will see a new `venv/` folder appear inside `c:\SBC\`. This is normal.

### Step 3 — Activate the Virtual Environment
```bash
# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# On Windows (Command Prompt):
.\venv\Scripts\activate.bat
```
After activating, your terminal prompt will change to show `(venv)` at the start. This means it is active.

### Step 4 — Install All Dependencies
```bash
pip install -r requirements.txt
```
This will automatically install all required libraries (OpenAI, pdfplumber, openpyxl, etc.).

### Step 5 — Set Up Your API Key
Make sure the `.env` file exists at `c:\SBC\.env` with your OpenAI key:
```env
OPENAI_API_KEY=sk-your-api-key-here
```

> ✅ You only need to do Steps 1-5 **once**. After that, just activate the venv (Step 3) each time you open a new terminal.

---

## 🤔 What Does This Platform Do?

You give it a PDF from any insurance carrier (Aetna, UHC, Anthem, etc.).
It reads the PDF automatically, extracts all the plan details, and fills them into your Excel template — just like a human would, but in seconds.

---

## 🚀 How to Run It — Step by Step

### Step 1 — Drop Your PDF Files In
Place one or more SBC PDF files into this folder:
```
c:\SBC\data\input_pdfs\
```
That's it! You don't need to rename them or do anything else.

---

### Step 2 — Run the Pipeline

Open a terminal (Command Prompt or PowerShell) inside `c:\SBC\` and type:

```bash
python -m src.pipeline
```

The system will process each PDF automatically. You will see messages like:
```
Processing Aetna.pdf...
Successfully extracted Aetna.pdf.
Writing consolidated Excel file...
Pipeline Complete!
```

---

### Step 3 — Get Your Output

Once it finishes, open this folder to find your results:
```
c:\SBC\data\output\05_final_excel\
```

You will find a single Excel file called `final_batch_output.xlsx`.

Open it and you will see:
- ✅ One tab per carrier (e.g., "Aetna", "UHC", "Anthem")
- ✅ All plan details filled in automatically
- ✅ Dollar values with `$` symbol (e.g., `$35`)
- ✅ Percentages with `%` symbol (e.g., `20%`)
- ✅ "No Charge" converted to `$0`

---

## 📂 What's Inside Each Output Folder?

| Folder | What's Inside |
| :--- | :--- |
| `03_parsed_json/` | The raw data extracted from each PDF (JSON format) |
| `04_reports/` | Quality check reports showing confidence scores |
| `05_final_excel/` | ⭐ Your final, filled-in Excel files |

---

## ➕ How to Add a New PDF Format

You **don't need to change any code!** Just:
1. Drop the new PDF into `data\input_pdfs\`
2. Run the pipeline again

The AI understands all carrier formats automatically.

---

## ➕ How to Add a New Field to the Excel Output

1. Open `src\schemas\master_schema.py`
2. Add a new field (e.g., `chiropractic_copay: Optional[str] = None`)
3. Open `configs\template_mapping.json`
4. Add the Excel cell for that field (e.g., `"chiropractic.copay": "D100"`)
5. Run the pipeline — the AI will automatically start extracting it!

---

## ⚙️ Important Files to Know

| File | Purpose |
| :--- | :--- |
| `.env` | Holds your secret OpenAI API key (never share this) |
| `configs/template_mapping.json` | Maps each data field to an Excel cell (e.g., `D13`) |
| `src/schemas/master_schema.py` | Defines what fields to look for in the PDF |
| `data/Template/Current Plan - Template.xlsx` | Your blank Excel master template |

---

## ❌ Common Problems & Fixes

| Problem | Fix |
| :--- | :--- |
| `No PDFs found!` | Check that your PDFs are in `data\input_pdfs\` |
| `API key error` | Make sure your `.env` file is in `c:\SBC\` with a valid `OPENAI_API_KEY` |
| Fields appear blank in Excel | Check that the row numbers in `template_mapping.json` match your template |

---

## 📞 Summary — In Simple Words

```
PDF Files  ──►  AI Reads & Understands  ──►  Fills Your Excel Template
(Any carrier)     (OpenAI GPT-4o)           (data/output/05_final_excel/)
```

That's it. Drop PDFs in → Run the command → Get the Excel output. 🎉
