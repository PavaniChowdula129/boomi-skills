# Marketplace GraphQL API

Public, unauthenticated API for querying the Boomi Marketplace catalog at `marketplace.boomi.com` (formerly `discover.boomi.com`).

## Endpoint

```
POST https://platform.boomi.com/graphql
Content-Type: application/json
```

No authentication required.

## Query

```json
{
  "query": "{ catalogListings(input: { catalogListingTagFilter: \"<filter>\", catalogListingStatus: [PUBLISHED] }) { totalCount currentPageSize catalogListings { slug publishedDate listingMetaData { name description } listingArtifact { listingType artifactSourceId } createdByTags { listingTag { categoryCode name id } } listingTags { listingTag { categoryCode name id } } numberOfInstalls } } }"
}
```

## Key fields

| Field | Purpose |
|-------|---------|
| `listingMetaData.name` | Recipe display name |
| `listingMetaData.description` | What the recipe does |
| `listingArtifact.artifactSourceId` | Bundle ID — used to install via Bundle API |
| `listingArtifact.listingType` | Always filter to `RECIPE` — the only installable type |
| `slug` | URL path segment, also useful as folder name |
| `numberOfInstalls` | Popularity indicator |

## Required filter: Recipes only

Always include the Recipe asset type filter. Other listing types (`ACCELERATOR`, `PRE_INSTALLED`) have no `artifactSourceId` and cannot be installed via the Bundle API.

```
listingTags.listingTag.categoryCode = 'solution_asset_type' and listingTags.listingTag.name = 'Recipe'
```

This is combined with any user-specified filters using AND:

```
(listingTags.listingTag.categoryCode = 'solution_asset_type' and listingTags.listingTag.name = 'Recipe') and (listingTags.listingTag.categoryCode = 'solution_app' and listingTags.listingTag.name = 'Salesforce')
```

Use `in` for multiple values within a category:

```
listingTags.listingTag.name in ('Salesforce', 'ServiceNow')
```

### Category codes

| Code | Examples |
|------|----------|
| `solution_asset_type` | Always filter to `Recipe` (see required filter above) |
| `solution_app` | Salesforce, ServiceNow, Stripe, Workday, etc. |
| `solution_function` | Analytics, Finance, Human Resources, IT, Sales |
| `solution_usecase` | AI, Data Management, Lead-to-Cash, Order-to-Cash |
| `solution_service_type` | Integration, DataHub, B2B/EDI, API Management |
| `solution_created_by` | Boomi, Accenture, Infosys, Deloitte |