#!/usr/bin/env python3
"""Retrieve a synthetic FHIR Patient by leveraging Lang2FHIR search helpers."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
LANG2FHIR_SRC = REPO_ROOT / "lang2fhir"
if str(LANG2FHIR_SRC) not in sys.path:
    sys.path.append(str(LANG2FHIR_SRC))

try:
    from lang2fhir_tutorial import Lang2FHIRClient, Lang2FHIRConfig  # type: ignore
except ImportError as exc:  # pragma: no cover - defensive guard for path issues
    raise SystemExit(
        "Could not import Lang2FHIR helpers. Confirm the lang2fhir repo sits next to Angy_chatbot."
    ) from exc

load_dotenv(dotenv_path=REPO_ROOT / ".env", override=False)
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=False)

DEFAULT_FHIR_BASE = os.getenv(
    "PHENOML_SYNTHETIC_FHIR_BASE",
    "https://experiment.app.pheno.ml/synthetic/fhir",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch a synthetic patient using Lang2FHIR and the sandbox FHIR API",
    )
    parser.add_argument(
        "--patient-id",
        help="FHIR id of the synthetic patient to fetch directly",
    )
    parser.add_argument(
        "--query-text",
        help="Natural language description when the patient id is unknown",
    )
    parser.add_argument(
        "--save-json",
        type=Path,
        help="Optional file to store the returned JSON payloads",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print intermediate Lang2FHIR and FHIR responses",
    )
    return parser.parse_args()


def ensure_credentials(config: Lang2FHIRConfig) -> None:
    has_basic = bool(config.basic_auth_token)
    has_user_pass = bool(config.username and config.password)
    has_direct_token = bool(config.access_token)
    if not (has_basic or has_user_pass or has_direct_token):
        raise SystemExit(
            "Set PHENOML_BASIC_TOKEN or PHENOML_USERNAME/PHENOML_PASSWORD (or PHENOML_ACCESS_TOKEN)."
        )


def build_query_params(search_response: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("params", "parameters", "search_parameters", "queryParams"):
        value = search_response.get(key)
        if isinstance(value, dict) and value:
            return value
    nested = search_response.get("search") or search_response.get("payload")
    if isinstance(nested, dict):
        nested_params = build_query_params(nested)
        if nested_params:
            return nested_params
    for key in ("query", "parameter_string", "search_string"):
        value = search_response.get(key)
        if isinstance(value, str) and value.strip():
            return {k: v for k, v in parse_qsl(value, keep_blank_values=False)}
    raise ValueError("Lang2FHIR search response did not contain recognizable parameters")


def fetch_patient_by_id(
    token: str,
    patient_id: str,
    *,
    base_url: str,
    timeout: int,
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/Patient/{patient_id}"
    headers = {
        "accept": "application/fhir+json",
        "authorization": f"Bearer {token}",
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    if response.status_code != 200:
        raise RuntimeError(f"FHIR request failed ({response.status_code}): {response.text}")
    return response.json()


def search_patient_bundle(
    token: str,
    params: Dict[str, Any],
    *,
    base_url: str,
    timeout: int,
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/Patient"
    headers = {
        "accept": "application/fhir+json",
        "authorization": f"Bearer {token}",
    }
    response = requests.get(url, headers=headers, params=params, timeout=timeout)
    if response.status_code != 200:
        raise RuntimeError(f"FHIR search failed ({response.status_code}): {response.text}")
    return response.json()


def extract_first_patient(bundle: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    entries = bundle.get("entry")
    if not isinstance(entries, list):
        return None
    for entry in entries:
        resource = entry.get("resource") if isinstance(entry, dict) else None
        if isinstance(resource, dict) and resource.get("resourceType") == "Patient":
            return resource
    return None


def main() -> None:
    args = parse_args()
    if not args.patient_id and not args.query_text:
        raise SystemExit("Provide --patient-id or --query-text so the script knows how to proceed.")

    config = Lang2FHIRConfig()
    ensure_credentials(config)
    client = Lang2FHIRClient(config)
    token = client.authenticate()

    base_url = DEFAULT_FHIR_BASE
    timeout = config.timeout_seconds
    patient_id = args.patient_id
    search_bundle: Optional[Dict[str, Any]] = None

    if args.query_text:
        search_response = client.generate_search_params(
            text=args.query_text,
            resource_type="Patient",
        )
        if args.verbose:
            print("Lang2FHIR search response:\n" + json.dumps(search_response, indent=2))
        params = build_query_params(search_response)
        search_bundle = search_patient_bundle(
            token,
            params,
            base_url=base_url,
            timeout=timeout,
        )
        if args.verbose:
            print("FHIR search bundle:\n" + json.dumps(search_bundle, indent=2))
        first_patient = extract_first_patient(search_bundle)
        if not first_patient:
            raise SystemExit(
                "No Patient resource returned by the sandbox. Adjust the query text or verify sandbox contents."
            )
        patient_id = first_patient.get("id")
        if not patient_id:
            raise SystemExit("Patient resource missing an id field; rerun with --verbose for details.")
        if args.verbose:
            print(f"Using patient id {patient_id} from the first bundle entry")

    assert patient_id  # for type checkers
    patient_data = fetch_patient_by_id(
        token,
        patient_id,
        base_url=base_url,
        timeout=timeout,
    )
    print(json.dumps(patient_data, indent=2))

    if args.save_json:
        payload = {
            "patient": patient_data,
            "search_bundle": search_bundle,
        }
        args.save_json.parent.mkdir(parents=True, exist_ok=True)
        args.save_json.write_text(json.dumps(payload, indent=2))
        print(f"Saved output to {args.save_json}")


if __name__ == "__main__":
    main()
