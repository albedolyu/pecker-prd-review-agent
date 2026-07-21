> **Synthetic demo data:** This fictional PRD exists only to demonstrate the public Pecker review workflow. It contains no customer or company material.

# Lantern Notes Search

## Goal

Make search better for teams that keep meeting notes in Lantern Notes.

## Proposed experience

A user types a phrase and sees matching notes, people, and project labels in one list.

Results should feel fast. Ranking details are TBD before implementation.

## Data

The search index reads generic `notes` and `note_members` tables from the demo database. A fictional integration can call `https://api.example.test/v1/search` during local demonstrations.

## Open questions

- How should spelling mistakes behave?
- What should a user see when indexing fails?
- Which result fields are required?
