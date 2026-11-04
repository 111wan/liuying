---
name: anime-image-blending
description: Blend an anime or illustrated character naturally into a photographic background by matching luminance, shaping environmental light, and unifying color. Use for compositing or “溶图” requests involving illustrated characters and real scenes.
---

# Anime Image Blending

Make the character feel lit by the scene instead of looking like a bright cutout placed on top. Keep the character recognizable and preserve the background unless the user asks for broader changes. Use the editor and source files the user provides; explain steps when they ask for a tutorial, and edit the image when they ask for a finished composite and suitable tools or files are available.

## Workflow

1. **Build the composition.** Place and scale the character in the scene. Check perspective, contact points, and whether foreground objects should overlap the character. Preserve a clean source layer when practical.
2. **Match luminance first.** Temporarily view both layers in grayscale. Adjust the character's overall exposure, contrast, and black/white points until its tonal range sits plausibly within the background. Avoid solving a mismatch with color alone.
3. **Follow the scene's light.** Identify the strongest light direction and ambient shadow in the background. Use broad, soft gradients or feathered masks on duplicated character layers or adjustment layers to create local light and shadow. Keep the transitions gradual and let the scene determine which side is brighter; do not assume a fixed left/right direction.
4. **Integrate edges and overlap.** Refine masks around hair, clothing, and other fine edges. Use modest feathering and subtle edge lighting or environmental color only where supported by the scene. Keep important facial features and silhouette detail legible.
5. **Restore color and unify.** Return to color, then make restrained adjustments to temperature, saturation, and contrast so the character and background share a palette. Add grain, blur, or atmospheric effects only when the source scene calls for them.
6. **Review together.** Inspect the whole composition and a close view. Check that the character's brightness, shadow direction, edge softness, and color still make sense at normal viewing size; revise the least convincing mismatch first.

## Practical guidance

- In After Effects, this can be built with duplicated character layers, masks, feathering, curves/levels, and gradient-based exposure shaping. Equivalent adjustment and mask tools are fine in other editors.
- Treat grayscale as a diagnostic step, not a requirement to deliver a monochrome image.
- Prefer broad tonal and lighting adjustments before small decorative effects. The main blending cues are compatible luminance, directional light, soft transitions, and shared color.
- If a key light direction or desired look is ambiguous, infer it from the background and show the user a reasonable result; ask only when multiple plausible choices would materially change the composition.
- Do not claim exact settings from a reference tutorial unless those settings are visible or provided. Adapt the method to the actual images and explain any meaningful tradeoffs.
