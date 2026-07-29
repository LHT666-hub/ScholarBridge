# Setup and verification

ScholarBridge uses only the Python standard library and requires Python 3.10 or newer.

## Verify

```powershell
python scripts/doctor.py
python -m unittest discover -s tests -v
```

If Windows routes `python` to the Microsoft Store, use an existing interpreter explicitly, for example:

```powershell
& "C:\anaconda3\python.exe" -m unittest discover -s tests -v
```

## Dry run

```powershell
python scripts/fetch_open_pdfs.py assets/input.example.csv `
  --output-dir literature_run/acquisition `
  --email researcher@example.edu
```

## Execute a bounded run

```powershell
python scripts/fetch_open_pdfs.py assets/input.example.csv `
  --output-dir literature_run/acquisition `
  --email researcher@example.edu `
  --max-records 10 `
  --execute
```

## Package

```powershell
python scripts/package_skill.py --output dist/skill.zip
```
