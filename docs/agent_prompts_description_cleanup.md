# Description Cleanup Agent Prompts

## Agent 1: Bellevue Cluster

```text
Continue the description-cleanup pass in `C:\Users\liam1\blender_buildings`.

Your assigned scope:
Work only on Bellevue Avenue files under:
- `C:\Users\liam1\blender_buildings\params`

Goal:
Revise and improve remaining templated human-readable building descriptions in Bellevue Avenue parameter JSON files.

Edit only descriptive prose fields such as:
- `facade_description`
- `storefront_description`
- `photo_observations.storefront_description`
- `storefront.description`

Do not change:
- dimensions
- counts
- heights
- lot/site data
- typology flags
- materials unless a prose field needs better wording
- confidence values
- timestamps
- addresses
- structural JSON layout
- any numeric or structural/building-logic data unless required to keep JSON valid

Style requirements:
- Replace template boilerplate with building-specific language
- Write concise architectural/site observations
- Distinguish clearly between bay-and-gable houses, semi-detached pairs, altered residential buildings, mixed-use conversions, and modernized/infill conditions
- Avoid phrases like “presents a street-facing facade within the Kensington Market HCD”
- Avoid pasted HCD note text
- Avoid invented heritage claims not supported by the file
- Preserve uncertainty if the file is low-confidence, partial, dark, blurry, rear-facing, or missing observation detail
- If a file already has cleaned, specific prose, skip it

Recommended workflow:
1. Find remaining Bellevue files with templated descriptions using `rg`
2. Pick a coherent Bellevue batch
3. Inspect `facade_description`, `photo_observations`, `storefront`, and storefront description fields
4. Rewrite only allowed prose fields
5. Validate edited JSON with `jq empty`
6. Report updated files

Important heuristics:
- If `photo_observations` is null, keep wording conservative
- If direct observation text exists, use it to sharpen the description
- Treat adjacent row-house files consistently
- For aggregate multi-address files, describe the group rather than inventing bay-specific detail

Current context:
- Oxford, Lippincott, and Casimir tracked boilerplate cleanup is complete
- Many earlier Augusta / Nassau / Baldwin / College / Spadina files are already done
- Visible Bellevue holdouts include:
  - `C:\Users\liam1\blender_buildings\params\100_Bellevue_Ave.json`
  - `C:\Users\liam1\blender_buildings\params\106_Bellevue_Ave.json`
  - `C:\Users\liam1\blender_buildings\params\108_Bellevue_Ave.json`

Output format:
- List updated files
- State that `jq empty` passed
- Mention any files kept cautious due to weak or missing direct photo-observation detail
```

## Agent 2: Nassau Cluster

```text
Continue the description-cleanup pass in `C:\Users\liam1\blender_buildings`.

Your assigned scope:
Work only on Nassau Street files under:
- `C:\Users\liam1\blender_buildings\params`

Goal:
Revise and improve remaining templated human-readable building descriptions in Nassau Street parameter JSON files.

Edit only descriptive prose fields such as:
- `facade_description`
- `storefront_description`
- `photo_observations.storefront_description`
- `storefront.description`

Do not change:
- dimensions
- counts
- heights
- lot/site data
- typology flags
- materials unless a prose field needs better wording
- confidence values
- timestamps
- addresses
- structural JSON layout
- any numeric or structural/building-logic data unless required to keep JSON valid

Style requirements:
- Replace template boilerplate with building-specific language
- Write concise architectural/site observations
- Distinguish between modest residential buildings, house-form commercial conversions, mixed-use storefronts, and grouped/aggregate files
- Avoid phrases like “presents a street-facing facade within the Kensington Market HCD”
- Avoid pasted HCD note text
- Avoid invented heritage claims not supported by the file
- Preserve uncertainty where the photo is partial, blurry, absent, or low-confidence
- If a file already has cleaned, specific prose, skip it

Recommended workflow:
1. Find remaining Nassau files with templated descriptions using `rg`
2. Pick a coherent Nassau batch
3. Inspect `facade_description`, `photo_observations`, `storefront`, and storefront description fields
4. Rewrite only allowed prose fields
5. Validate edited JSON with `jq empty`
6. Report updated files

Important heuristics:
- If `photo_observations` is null, do not over-describe
- If storefront metadata exists without rich observation text, describe mixed-use/commercial conditions conservatively
- Treat adjacent addresses consistently
- For aggregate multi-address files, describe the visible shared form rather than inventing address-by-address details

Current context:
- Oxford, Lippincott, and Casimir tracked boilerplate cleanup is complete
- Many earlier Nassau files were already improved, but holdouts remain
- Visible Nassau holdouts include:
  - `C:\Users\liam1\blender_buildings\params\104_Nassau_St.json`

Output format:
- List updated files
- State that `jq empty` passed
- Mention any files kept cautious due to weak or missing direct photo-observation detail
```

## Agent 3: Baldwin and Misc Holdouts

```text
Continue the description-cleanup pass in `C:\Users\liam1\blender_buildings`.

Your assigned scope:
Work on remaining non-Bellevue, non-Nassau holdout files, starting with Baldwin Street or small mixed clusters under:
- `C:\Users\liam1\blender_buildings\params`

Do not touch Bellevue Avenue files or Nassau Street files in this run.

Goal:
Revise and improve remaining templated human-readable building descriptions in assigned non-Bellevue, non-Nassau parameter JSON files.

Edit only descriptive prose fields such as:
- `facade_description`
- `storefront_description`
- `photo_observations.storefront_description`
- `storefront.description`

Do not change:
- dimensions
- counts
- heights
- lot/site data
- typology flags
- materials unless a prose field needs better wording
- confidence values
- timestamps
- addresses
- structural JSON layout
- any numeric or structural/building-logic data unless required to keep JSON valid

Style requirements:
- Replace template boilerplate with building-specific language
- Write concise architectural/site observations
- Distinguish clearly between altered historic rows, mixed-use conversions, contemporary infill, modern commercial buildings, and rear/side/laneway views
- Avoid phrases like “presents a street-facing facade within the Kensington Market HCD”
- Avoid pasted HCD note text
- Avoid invented heritage claims not supported by the file
- Preserve uncertainty where the record is partial, blurry, absent, rear-facing, or low-confidence
- If a file already has cleaned, specific prose, skip it

Recommended workflow:
1. Find remaining templated files with `rg`
2. Exclude Bellevue Avenue and Nassau Street files
3. Pick a coherent small street batch
4. Inspect `facade_description`, `photo_observations`, `storefront`, and storefront description fields
5. Rewrite only allowed prose fields
6. Validate edited JSON with `jq empty`
7. Report updated files

Important heuristics:
- If `photo_observations` is null, keep wording conservative
- If a file is a rear or side view, do not describe it as a full street-facing facade
- If storefront metadata exists but observation detail is weak, describe it conservatively
- For aggregate files, describe the group rather than inventing detailed differences between units

Current context:
- Oxford, Lippincott, and Casimir tracked boilerplate cleanup is complete
- Recent Baldwin files already completed:
  - `147_Baldwin_St.json`
  - `149_Baldwin_St.json`
  - `188_Baldwin_St.json`
  - `190_Baldwin_St.json`
- Start with other remaining Baldwin or nearby non-Bellevue/non-Nassau clusters

Output format:
- List updated files
- State that `jq empty` passed
- Mention any files kept cautious due to weak or missing direct photo-observation detail
```

## Agent 4: Reviewer

```text
Review completed description-cleanup edits in `C:\Users\liam1\blender_buildings\params`.

Your role:
You are not the primary rewriter. You are the reviewer for output produced by the other agents. Your job is to catch weak descriptions, invented claims, leftover boilerplate, and inconsistent handling of uncertain files.

Scope:
- Review only files edited by the worker agents in the current pass
- You may make small corrective edits if needed, but do not expand scope into unrelated streets

Primary review targets:
- `facade_description`
- `storefront_description`
- `photo_observations.storefront_description`
- `storefront.description`

Do not change:
- dimensions
- counts
- heights
- lot/site data
- typology flags
- materials unless needed for prose consistency
- confidence values
- timestamps
- addresses
- structural JSON layout
- any numeric or structural/building-logic data unless required to keep JSON valid

Review checklist:
- Remove leftover template wording such as:
  - “presents a street-facing facade within the Kensington Market HCD”
  - “presents a row-house facade within the Kensington Market HCD”
  - “presents a bay-and-gable domestic facade within the Kensington Market HCD”
  - pasted `HCD note:` or statement-of-contribution language
- Check that rear, side, laneway, or partial views are not described as full street-facing facades
- Check that storefronts are not invented where none are visible
- Check that modern infill is not described as historic fabric unless the file supports that reading
- Check that aggregate multi-address files describe a group consistently rather than fabricating bay-by-bay differences
- Check that low-detail or null `photo_observations` files use cautious wording
- Check that repeated adjacent buildings are described consistently without becoming copy-paste boilerplate

If you find problems:
- Make only targeted prose fixes
- Keep wording concise and factual
- Validate edited JSON with `jq empty`

Suggested review workflow:
1. Take the file list returned by the worker agents
2. Search those files for leftover boilerplate with `rg`
3. Read the edited description fields and compare them to `photo_observations`
4. Fix only the files that still overclaim, underdescribe, or retain templated language
5. Validate changed files with `jq empty`
6. Report findings

Output format:
- Findings first, ordered by severity
- For each issue, name the file and explain the problem briefly
- If you made fixes, list corrected files
- State whether `jq empty` passed
- If no issues were found, say so explicitly
```
