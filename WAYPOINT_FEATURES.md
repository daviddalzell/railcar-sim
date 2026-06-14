# WAYPOINT
### The Smart Operations Companion for Model Railroaders

> **What is Waypoint?**
> Waypoint is a web-based management tool that brings real railroad operations to your model layout. It tracks your rolling stock, automates waybill routing, and guides every car through a prototypical operating session — so you can focus on the fun part.

---

> **Key Facts**
> - AI identifies car type, reporting marks, road number, and color from a single photo
> - Supports Claude, GPT-4o, Gemini, and local Ollama vision models
> - Waybill cards support up to 4 sequential movements per car
> - Fast clock simulates prototypical railroad time at 1×, 2×, 4×, 6×, or 12× speed
> - Full layout backup and restore in a single ZIP file

---

## Smart Car Roster

Build your fleet in minutes, not hours.

- Photograph any car — AI instantly fills in car type, reporting marks, road number, and color
- Choose your AI engine: Claude (Anthropic), GPT-4o (OpenAI), Gemini, or a local Ollama model
- Generate a stylized illustration of each car with one click
- Add cars manually or select photos from a shared library
- Edit any detail at any time; delete cars cleanly with full history cleanup

---

## Waybill System

Prototype-accurate car routing without the paperwork.

- Create waybills with origin, destination, commodity, and assigned industry
- Stack up to 4 sequential movement cards on a single car
- Generate waybills automatically from your layout's industries
- Auto-assign unassigned waybills to available cars by car type and routing logic
- Define commodity-to-car-type rules (e.g. grain → covered hopper, crude oil → tank car)
- Advance a car's active waybill slot with a single tap

---

## Layout Setup

Model your railroad once, operate it forever.

- Define locations by type: Yard, Industry, Staging, or Storage
- Create industries and assign roles: Consumer (receives), Producer (ships), or Transload (both)
- Use ✨ AI Suggest to automatically fill in commodities, car types, and role from an industry name
- Specify which car types and commodities each industry accepts
- Seed a starter set of commodity mappings or build your own from scratch
- Use ✨ on any commodity to get an AI suggestion for the correct car type
- Collapse the Commodity → Car Type panel to save space when not in use
- Configure the Fast Clock start time and speed multiplier

---

## Operating Sessions

Run a realistic ops session from plan to wrap-up.

- Session planner lists every car move needed: arrivals, departures, and cars to spot from storage
- Car thumbnails and reporting marks visible at a glance in the switch list
- Mark each car Done (moved) or CP (Car Placement — temporary hold)
- End session: waybill slots auto-advance and car locations update automatically
- Session state persists across browser refresh — pick up where you left off
- Read-only operations view shows every car, its current location, and active waybill

---

## Fast Clock

Simulate prototypical railroad time during every operating session.

- Fast clock starts automatically when a session begins
- Configure start time (e.g. 08:00) and speed multiplier in Layout Setup
- Speed options: 1× (real time), 2×, 4×, 6×, or 12×
- Pause and resume the clock at any time during a session
- Clock state is stored server-side — resuming after a page refresh shows the correct model time
- Supports multiple operators: all clients read from the same authoritative clock

---

## AI Features

Reduce manual data entry at every step.

- **Car identification** — Upload a photo and AI fills in car type, reporting marks, road number, and color
- **Stylized illustration** — Generate an artistic rendering of any car with one click
- **Industry suggest** — Type an industry name and click ✨ AI Suggest to auto-fill commodities, car types, and role
- **Commodity suggest** — Click ✨ next to any commodity to get the correct car type automatically
- AI calls automatically retry on transient provider errors (rate limits, overloads) before failing
- Supported providers: Gemini, Claude (Anthropic), GPT-4o (OpenAI), or a local Ollama model

---

## Data & Backup

Your layout data, safe and portable.

- Export a complete snapshot: locations, industries, cars, waybills, photos, and movement logs
- Restore any backup with a single import — great for sharing layouts or recovering from errors
- Purge orphaned photos to keep storage tidy
- Per-car movement history records the last 5 moves with timestamps and notes
