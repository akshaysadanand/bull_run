# Presets Feature — Design

## Overview

Add a preset selector to the main page that lets users load pre-configured ticker + custom URL combinations with one click. Presets are stored in a JSON file and can be saved from within the app.

## Architecture

```
Streamlit UI (app.py)
├── Preset Selector Row (dropdown + Run button + Save button)
├── scraper.py              unchanged
├── summarizer.py           unchanged
└── presets.json            NEW — preset definitions
```

No new modules. All changes are UI-level additions to `app.py` plus a data file. No new dependencies — Python's built-in `json` module handles the config.

## Components

### Presets Config (`presets.json`)

JSON array of preset objects in the project root:

```json
[
  {
    "name": "AST SpaceMobile",
    "ticker": "ASTS",
    "custom_urls": []
  },
  {
    "name": "Rocket Lab",
    "ticker": "RKLB",
    "custom_urls": []
  },
  {
    "name": "GameStop",
    "ticker": "GME",
    "custom_urls": []
  }
]
```

Each preset has:
- `name` — display label in the dropdown
- `ticker` — stock ticker symbol (uppercase)
- `custom_urls` — optional list of URLs for custom source scraping

### Preset Selector Row (in `app.py`)

A single horizontal row placed above the ticker input, containing:

- **Dropdown** — lists all presets by name; selecting one auto-fills the ticker and custom URLs fields below
- **Run button** (`▶`) — triggers "Get News" for the selected preset immediately (one-click experience)
- **Save button** (`+`) — saves the current ticker + custom URLs as a new preset to `presets.json`

**Behavior:**
- Loading presets happens at app startup via `json.load()` on `presets.json`
- Selecting a preset from the dropdown updates the ticker text input and custom URLs text area
- The ticker input remains editable — users can override a preset's value
- The Run button is disabled while a news pipeline is running (same as existing "Get News" disabled state)
- The Save button prompts for a preset name, then appends to `presets.json` with duplicate-name checking

### Save Preset Flow

1. User clicks "+ Save"
2. A text input appears asking for the preset name
3. On confirmation:
   - If name already exists → show error "Preset 'X' already exists"
   - If name is new → append to `presets.json`, reload presets, show success toast

## Data Flow

1. App starts → loads `presets.json` into a cached variable
2. User selects a preset from dropdown → ticker and custom URLs fields auto-populate
3. User clicks "▶ Run" → same flow as existing "Get News" button (scrape → summarize → display)
4. User clicks "+ Save" → current ticker + URLs written to `presets.json` → presets reloaded

## Error Handling

| Scenario | Behavior |
|---|---|
| `presets.json` missing | Show info message "No presets yet — save one from the main page or create `presets.json`" |
| `presets.json` has invalid JSON | Show error with filename, fall back to empty preset list |
| Duplicate preset name on save | Show error "Preset 'X' already exists — choose a different name" |
| Empty preset name on save | Show error "Preset name is required" |

## File Structure

```
bull_run/
├── app.py                      # add preset selector, auto-load, save button
├── presets.json                # NEW — default presets (ASTS, RKLB, GME)
├── scraper.py                  # unchanged
├── summarizer.py               # unchanged
└── pyproject.toml              # unchanged
```

## Testing

- Verify `presets.json` loads correctly at startup
- Verify selecting a preset auto-fills ticker and custom URLs
- Verify Run button triggers the news pipeline with preset data
- Verify Save button appends new preset to `presets.json`
- Verify duplicate name rejection on save
- Verify graceful handling of missing or malformed `presets.json`
