---
version: "alpha"
name: "Stratum - System Coordination Framework"
description: "Stratum System Feature Section is designed for highlighting product capabilities and value points. Key features include reusable structure, responsive behavior, and production-ready presentation. It is suitable for component libraries and responsive product interfaces."
colors:
  primary: "#A3907A"
  secondary: "#8C8273"
  tertiary: "#A1AE7A"
  neutral: "#7A756D"
  background: "#EAE5DF"
  surface: "#A3907A"
  text-primary: "#8C8273"
  text-secondary: "#7A756D"
  border: "#EAE5DF"
  accent: "#A3907A"
typography:
  display-lg:
    fontFamily: "Inter"
    fontSize: "96px"
    fontWeight: 200
    lineHeight: "96px"
    letterSpacing: "-0.025em"
    textTransform: "uppercase"
  body-md:
    fontFamily: "Inter"
    fontSize: "12px"
    fontWeight: 200
    lineHeight: "16px"
  label-md:
    fontFamily: "Inter"
    fontSize: "14px"
    fontWeight: 300
    lineHeight: "20px"
rounded:
  md: "5px"
spacing:
  base: "4px"
  sm: "1px"
  md: "4px"
  lg: "8px"
  xl: "10px"
  gap: "6px"
  card-padding: "8px"
  section-padding: "24px"
components:
  button-primary:
    textColor: "#2C2C2A"
    typography: "{typography.label-md}"
    rounded: "{rounded.md}"
    padding: "14px"
  button-link:
    textColor: "{colors.secondary}"
    rounded: "0px"
    padding: "0px"
  card:
    rounded: "{rounded.md}"
    padding: "16px"
---

## Overview

- **Composition cues:**
  - Layout: Grid
  - Content Width: Bounded
  - Framing: Glassy
  - Grid: Strong

## Colors

The color system uses light mode with #A3907A as the main accent and #7A756D as the neutral foundation.

- **Primary (#A3907A):** Main accent and emphasis color.
- **Secondary (#8C8273):** Supporting accent for secondary emphasis.
- **Tertiary (#A1AE7A):** Reserved accent for supporting contrast moments.
- **Neutral (#7A756D):** Neutral foundation for backgrounds, surfaces, and supporting chrome.

- **Usage:** Background: #EAE5DF; Surface: #A3907A; Text Primary: #8C8273; Text Secondary: #7A756D; Border: #EAE5DF; Accent: #A3907A

- **Gradients:** bg-gradient-to-b from-[#ffffff] to-[#DCD6CC], bg-gradient-to-b from-[#ffffff] to-[#EAE5DF], bg-gradient-to-b from-[#FDFBF7] to-[#F5F2EB], hover:bg-gradient-to-r hover:from-black/[0.02] hover:to-transparent

## Typography

Typography relies on Inter across display, body, and utility text.

- **Display (`display-lg`):** Inter, 96px, weight 200, line-height 96px, letter-spacing -0.025em, uppercase.
- **Body (`body-md`):** Inter, 12px, weight 200, line-height 16px.
- **Labels (`label-md`):** Inter, 14px, weight 300, line-height 20px.

## Layout

Layout follows a grid composition with reusable spacing tokens. Preserve the grid, bounded structural frame before changing ornament or component styling. Use 4px as the base rhythm and let larger gaps step up from that cadence instead of introducing unrelated spacing values.

Treat the page as a grid / bounded composition, and keep that framing stable when adding or remixing sections.

- **Layout type:** Grid
- **Content width:** Bounded
- **Base unit:** 4px
- **Scale:** 1px, 4px, 8px, 10px, 12px, 14px, 16px, 20px
- **Section padding:** 24px, 56px
- **Card padding:** 8px, 12px, 16px, 18px
- **Gaps:** 6px, 8px, 12px, 16px

## Elevation & Depth

Depth is communicated through glass, border contrast, and reusable shadow or blur treatments. Keep those recipes consistent across hero panels, cards, and controls so the page reads as one material system.

Surfaces should read as glass first, with borders, shadows, and blur only reinforcing that material choice.

- **Surface style:** Glass
- **Borders:** 1px #EAE5DF; 1px #DCD6CC
- **Shadows:** rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgb(255, 255, 255) 0px 1px 0px 0px inset; rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.05) 0px 1px 2px 0px; rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.2) 0px 1px 2px 0px inset
- **Blur:** 12px, 24px

### Techniques
- **Gradient border shell:** Use a thin gradient border shell around the main card. Wrap the surface in an outer shell with 1px padding and a 6px radius. Drive the shell with linear-gradient(rgb(255, 255, 255), rgb(253, 251, 247), rgb(220, 214, 204)) so the edge reads like premium depth instead of a flat stroke. Keep the actual stroke understated so the gradient shell remains the hero edge treatment. Inset the real content surface inside the wrapper with a slightly smaller radius so the gradient only appears as a hairline frame.

## Shapes

Shapes rely on a tight radius system anchored by 2px and scaled across cards, buttons, and supporting surfaces. Icon geometry should stay compatible with that soft-to-controlled silhouette.

Use the radius family intentionally: larger surfaces can open up, but controls and badges should stay within the same rounded DNA instead of inventing sharper or pill-only exceptions.

- **Corner radii:** 2px, 3px, 4px, 5px, 6px, 8px
- **Icon treatment:** Linear
- **Icon sets:** Solar

## Components

Anchor interactions to the detected button styles. Reuse the existing card surface recipe for content blocks.

### Buttons
- **Primary:** text #2C2C2A, radius 5px, padding 14px, border 0px solid rgb(229, 231, 235).
- **Links:** text #8C8273, radius 0px, padding 0px, border 0px solid rgb(229, 231, 235).

### Cards and Surfaces
- **Card surface:** border 0px solid rgb(229, 231, 235), radius 5px, padding 16px, shadow rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgb(255, 255, 255) 0px 1px 0px 0px inset, rgba(0, 0, 0, 0.02) 0px -1px 1px 0px inset, blur 12px.

### Iconography
- **Treatment:** Linear.
- **Sets:** Solar.

## Do's and Don'ts

Use these constraints to keep future generations aligned with the current system instead of drifting into adjacent styles.

### Do
- Do use the primary palette as the main accent for emphasis and action states.
- Do keep spacing aligned to the detected 4px rhythm.
- Do reuse the Glass surface treatment consistently across cards and controls.
- Do keep corner radii within the detected 2px, 3px, 4px, 5px, 6px, 8px family.

### Don't
- Don't introduce extra accent colors outside the core palette roles unless the page needs a new semantic state.
- Don't mix unrelated shadow or blur recipes that break the current depth system.
- Don't exceed the detected moderate motion intensity without a deliberate reason.

## Motion

Motion feels controlled and interface-led across text, layout, and section transitions. Timing clusters around 150ms and 300ms. Easing favors ease and 0. Hover behavior focuses on color and text changes.

**Motion Level:** moderate

**Durations:** 150ms, 300ms, 1000ms

**Easings:** ease, 0, 0.2, 1), cubic-bezier(0.4, cubic-bezier(0

**Hover Patterns:** color, text, shadow
