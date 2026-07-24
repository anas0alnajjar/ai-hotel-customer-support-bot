# Nour Al-Sham Grand Hotel Seed Dataset

This directory contains a fully synthetic, versioned operational dataset for the fictional **Nour Al-Sham Grand Hotel**. It must never be presented as a real hotel or connected to real guests, payments, or reservations.

## Dataset v1.0.0

| Entity | Count |
|---|---:|
| Room types | 5 |
| Rooms | 22 |
| Pseudonymous guests | 6 |
| Simulated bookings | 8 |
| Simulated service requests | 3 |

The profile and room catalog are bilingual (`ar`, `en`). Two rooms intentionally have non-available operational states, bookings include assigned, unassigned, cancelled, checked-in, and checked-out cases, and service requests include room-service, maintenance, and emergency-guidance cases.

## Deterministic and safe seeding

- IDs are UUIDv5 values derived from versioned natural keys.
- Re-running the seed inserts missing rows only.
- Existing operational rows are not overwritten or reset.
- A natural key owned by a different ID fails with `SeedConflict`.
- The JSON file contains synthetic demonstration verification values only. MySQL stores PBKDF2-SHA256 hashes, never those raw values.

Run from the project root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\seed-hotel.ps1
```

## Demonstration booking cases

| Reference | Verification value | Purpose |
|---|---|---|
| `BKG-2026-0001` | `0101` | Confirmed assigned Standard King booking |
| `BKG-2026-0002` | `0202` | Pending assigned Standard Twin booking |
| `BKG-2026-0003` | `0303` | Confirmed unassigned Deluxe booking |
| `BKG-2026-0004` | `0404` | Family Suite capacity boundary |
| `BKG-2026-0006` | `0606` | Checked-in room with maintenance request |

These values are public test fixtures and MUST NOT be reused as a production verification design.
