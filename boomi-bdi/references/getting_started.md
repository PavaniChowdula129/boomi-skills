# Getting started (first-run setup)

Load this the first time a user sets up BDI in a workspace — when `bdi-env-check.sh` reports no `.env` or missing/rejected credentials, or when the user says they just installed the plugin, don't have a token yet, want to "connect their account", or asks how to begin. If credentials already check out, skip to § Already set up.

Keep it a short, friendly checklist, not a configuration form. This is the one place a user pastes a secret: never echo the token back, never log it, never put it in any output you display — it lives only in the workspace `.env`.

## The flow

The credential facts — the four `.env` keys, the region→host map, and what a 401 vs 403 means — are in SKILL.md § Credentials; this is the order to apply them in.

1. **Set all four keys.** The user creates and edits `.env` in the workspace directory themselves — by default you can't (and shouldn't) read or write it, so supply the key names and where each value comes from and let them fill it in:

    ```
    BDI_API_URL=https://api.rivery.io
    BDI_API_TOKEN=<BDI console → My Profile → API Tokens>
    BDI_ACCOUNT_ID=<account id>
    BDI_ENVIRONMENT_ID=<environment id>
    ```

    Both ids are 24-character hex strings, and both sit in the address bar whenever the user is in the BDI console — no lookup needed:

    ```
    https://console.rivery.io/dashboard/<account id>/<environment id>/dashboard?...
    ```

    The environment id there is whichever environment the console is currently showing, so have the user switch to the one they want to work in before copying. `BDI_API_URL` is the API host and is not the console address: it needs the `https://` scheme, no trailing slash, and it must match the account's region — SKILL.md § Credentials lists the four regional hosts. If the user can't produce the environment id, leave that line out for now and see § Finding the environment id below.

2. **Validate.** Run `bdi-env-check.sh` — it checks the vars and makes one live round-trip listing the environments the token can access. A missing-variable or "`.env` not found" error means the file isn't complete yet. A `401` is the same response for a bad token and for the wrong region host, so check the token paste first, then the host. A `403` means the token authenticated but lacks scope or access for that environment — see § Finding the environment id. On success it confirms the selected environment.

3. **Orient.** Tell the user that the environment in `.env` is the only environment you will act on, and that changing environments means editing that file. Then ask what they came to do and point them at the matching capability from SKILL.md § Scope / Capabilities and the reference for that task — don't recite the scripts inventory. A quick read of `bdi-flow.sh activities` optionally shows what's recently been moving data in the environment.

## Finding the environment id

If the user doesn't have the id, or the one they gave returns a `403`, run `bdi-env-check.sh` without `BDI_ENVIRONMENT_ID` set — it lists the environments and prints the line to paste. If it reports that more environments exist beyond the page it printed, enumerate them with `bdi-env.sh list --all` before recommending, so you aren't choosing from a truncated list.

Listing an environment is not the same as being able to work in it: a token can list every environment in the account and still `403` inside one it was never granted. `is_default` marks the account's default environment, not one this token can necessarily use — it is not a selection criterion. So when a `403` comes back, the fix is usually a different environment rather than a different token, and whoever issued the token knows which environments it carries grants for. Ask the user which environment their work belongs in, try that one, and only send them to the console to change the token's scopes once a granted environment still fails.

Talk in environment names with the user; the id goes in `.env`. Have the user add `BDI_ENVIRONMENT_ID=<id>` themselves (scripts read it only from `.env`; inline exports and blank placeholders don't take), then re-run `bdi-env-check.sh` to confirm it's selected.

## Empty environment list

If `bdi-env-check.sh` authenticates but lists no environments, the token is valid but has no environment grant — an admin grants it access to an environment in the BDI console, then re-run the check. Nothing has been saved, so there's nothing to undo; stop here until the grant is in place.

## Already set up

If `bdi-env-check.sh` passes and `BDI_ENVIRONMENT_ID` is selected, don't re-run setup. Confirm the active environment with the user and go straight to their task.
