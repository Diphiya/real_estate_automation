
# Cirrus Real Estate Automation

Automated **real estate exposé extraction, evaluation, and reporting** pipeline — designed to accelerate property deal evaluation by extracting data from exposés, populating Excel templates, and integrating with Google Workspace (Drive & Photos).

Cirrus Real Estate is a Berlin-based property developer. One of our core competitive advantages is **speed**: the best deals are often on the market for only a few hours. Currently, exposés are screened manually and data is transferred by hand into Excel templates, which is slow and error-prone. This project automates that workflow.

---

## Project Overview

The **Cirrus Real Estate Automation** prototype streamlines the property evaluation process by:

1. **Automatic Extraction**  
   Extracting key data points from property exposés (PDFs or other sources).  

2. **Template Population**  
   - **Part 1:** Fill the provided Excel evaluation template automatically with extracted exposé data.  
   - **Part 2:** Fill the Excel template with price data from the website to calculate realistic price per apartment.  

3. **Google Workspace Integration**  
   - Create a **Google Drive folder** for storing processed files.  
  
This automation ensures faster deal evaluation and reduces human error, while integrating seamlessly with internal tools.

---

##  Repository Structure

```
├── extract_expose_ollama.py        # Extracts key data from exposés using LLM
├── populate_excel_template.py      # Fills Excel template with extracted data
├── evaluate_prices.py              # Pulls online price data for comparison
├── google_drive.py                 # Automates Google Drive folder creation and upload
├── google_photos.py                # Automates Google Photos album creation
├── pipeline_ollama.py              # End-to-end pipeline orchestrator
├── config.json                     # Configuration file (credentials, paths)
├── extracted_data.json             # Raw extracted data
├── pipeline_result.json            # Processed results ready for Excel
├── extracted_photos/               # Downloaded exposé images
├── Excel_Template.xlsx             # Evaluation template for population
├── Case Study Exposé.pdf           # Sample exposé for testing
├── README.md                       # This file
└── other resources                 # Additional helpers, scripts, or datasets
```

---

## Features

- **Exposé Extraction:** Key data points automatically extracted from PDFs or online sources.  
- **Excel Template Population:** Two-step process: exposé data + real-world price data.  
- **Pipeline Integration:** End-to-end orchestration with a single command.  
- **Google Workspace Integration:** Drive & Photos folders created automatically.  
- **AI-Assisted Processing:** Optional LLM summarization for structured insights.  

---

## Installation

1. **Clone the repository**

```bash
git clone https://github.com/Diphiya/real_estate_automation.git
cd real_estate_automation
```

2. **Set up Python environment**

```bash
python3 -m venv venv
source venv/bin/activate            # macOS/Linux
venv\Scripts\activate             # Windows
```

3. **Install dependencies**

```bash
pip install -r requirements.txt
```

4. **Configure settings**

- Edit `config.json` with your Google Workspace credentials, output paths, and scraping parameters.  
- Ensure API keys (Google Drive / Photos) are stored securely.  

---

## Usage

### Run the full automation pipeline

```bash
python pipeline_ollama.py --input "Case Study Exposé.pdf" --excel_template "Excel_Template.xlsx"
```

### Steps performed:

1. Extracts key data from the exposé (`extract_expose_ollama.py`).  
2. Populates the Excel template with extracted data (`populate_excel_template.py`).  
3. Fetches online price data to update the Excel evaluation (`evaluate_prices.py`).  
4. Uploads files to Google Drive (`google_drive.py`).  
5. Creates a Google Photos album with all images (`google_photos.py`).  

---

## Configuration Example (`config.json`)

```json
{
  "scrape_targets": ["check24"],
  "output_folder": "./output",
  "google_drive_folder_id": "<YOUR_FOLDER_ID>",
  "google_photos_album_name": "Cirrus_Exposés",
  "credentials_file": "credentials.json",
  "price_per_sqm": 3200
}
```



