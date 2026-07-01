# Phase 2.1: OCR Architecture Refactoring

## Why this phase exists

The extraction facade had accumulated image normalization, OCR runtime discovery, preprocessing variants, AI HTTP integration, field voting, MRZ recovery, validation, and confidence scoring. This made changes risky because infrastructure concerns and extraction policy changed together.

## Current implementation review

`PassportExtractionService.extract(file_content, filename, content_type)` is the application-facing interface. Upload and re-extraction use cases depend on `IPassportExtractionService`, and persisted/API results contain `extracted_fields`, `overall_confidence`, `confidence_score`, and `mrz_raw`. Existing TD3 parsing, field validation, conservative enhancement, confidence scoring, and fallback behavior are working capabilities and remain in use.

## Problems addressed

- OCR engines were implemented in one adapter file and constructed through module-level conditionals.
- Preprocessing variants and image normalization were private methods on the facade.
- OpenAI request construction and response parsing were coupled to local extraction policy.
- Candidate aggregation was embedded in orchestration logic.
- Critical algorithms could not be tested independently without constructing the full service.

## Proposed and implemented architecture

The public service remains a facade. Focused collaborators now own infrastructure behavior:

```text
app/infrastructure/ocr/
  ai/openai_fallback.py
  confidence/scoring_service.py
  engines/
    factory.py
    easyocr_engine.py
    paddle_engine.py
    tesseract_engine.py
  extraction/text_extractor.py
  mrz/parser.py
  preprocessing/image_preprocessor.py
  voting/field_voter.py
  passport_extraction_service.py
```

Collaborators are injected through optional constructor parameters with production defaults. Engine adapters continue to implement `IOCREngine`. Canonical MRZ and confidence imports re-export the existing implementations, avoiding duplicate algorithms or premature rewrites.

MRZ recovery and visual field heuristics remain in the facade during this incremental phase. Moving them safely requires dedicated golden-image regression coverage and belongs to a subsequent Phase 2.1 refinement or the approved orchestration phase.

## Database changes

None. No migration is required and no persisted JSON structure changes.

## API compatibility review

- `IPassportExtractionService` is unchanged.
- `PassportExtractionService()` remains valid with no arguments.
- `extract(...)` parameters and `PassportExtractionResult` are unchanged.
- `app.infrastructure.ocr.engines.build_ocr_engine` remains available from the same import path.
- Confidence values and extracted-field merge rules use the existing implementations.

## Performance impact

The OCR work performed is unchanged. Engine instances remain lazy and cached per text extractor. Preprocessing remains in worker threads through the existing async facade. The refactor adds only local method dispatch; it does not add OCR passes, network calls, or image copies to the request path.

## Security impact

The AI adapter still uses a server-side environment key and sends only the normalized image plus local candidate fields. Parsed model output remains untrusted and is cleaned and plausibility-checked by the facade before merging. Upload validation and storage policy are unchanged.

## Testing strategy

- Unit-test image normalization dimensions and output format.
- Unit-test OCR text normalization/deduplication.
- Unit-test the existing exact-MRZ voting precedence.
- Unit-test Responses API output parsing.
- Run backend compilation and the existing backend suite in the project runtime.
- Run frontend lint/build because response contracts remain consumed by the UI.

## Rollback strategy

This phase has no migration or data rewrite. Rollback consists of restoring the previous `engines.py` and facade implementation. Stored submissions remain readable because schema and result shapes are unchanged. Each collaborator is internal and can be reverted independently.
