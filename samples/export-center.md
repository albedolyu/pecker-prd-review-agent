> **Synthetic demo data:** This fictional PRD exists only to demonstrate the public Pecker review workflow. It contains no customer or company material.

# Atlas Export Center

## Goal and target user

Operations analysts need one place to create and retrieve exports without waiting on an administrator.

## Scope

The first release supports CSV exports of fictional project and activity records. Scheduled exports and third-party delivery are out of scope.

## User flow

The user selects a dataset, chooses columns, and starts an export. The UI shows queued, running, completed, and failed states. A failed export includes a retry action.

## Interface contract

`POST /demo/exports` accepts a dataset name and a list of columns. It returns a generic export identifier and status. Invalid columns return a validation error.

## Acceptance criteria

- A 10,000-row synthetic export completes in the demo environment.
- A user can download a completed file from the export list.
- A failed export shows an error and retry action.

## Data handling

The demo stores export status in `export_jobs`. Retention duration and deletion behavior are TBD before implementation.
