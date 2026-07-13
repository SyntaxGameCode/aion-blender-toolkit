# Aion Blender Toolkit

![Version](https://img.shields.io/badge/version-0.4.30-blue)
![Blender](https://img.shields.io/badge/Blender-5.1%2B-orange)
![Status](https://img.shields.io/badge/status-experimental-yellow)

Blender addon for importing Aion Classic client levels and assets into Blender.

## Features

- Level folder import with separate Visual and Collision modes.
- Single CGF/CGA mesh import.
- Terrain mesh preview with terrain material blending preview.
- DDS texture/material loading for supported assets.
- Textured water/lava surface preview.
- Static deferred light import.
- Mission PlaceableObject import.
- Animated texture sequence playback.
- Shader UV scroll / TexShift animation.
- Experimental CGA controller rotation animation.
- Optional ParticleEffect preview.

## Installation

1. Download the release zip, for example `blender_aion_importer-0.4.30.zip`.
2. Open Blender.
3. Go to **Edit > Preferences > Add-ons**.
4. Click **Install from Disk** and select the zip.
5. Enable **Aion Importer**.

## Usage

### Level Folder

1. Open **File > Import > Aion Level Folder**.
2. Select an unpacked level folder containing `leveldata.xml`.
3. Set **Client Root** to your local unpacked Aion client directory.
4. Choose **Import Mode**:
   - **Visual** imports the visible scene and supported visual preview layers.
   - **Collision** imports terrain heightfield and collision geometry only.

To import both visual and collision geometry, run the import twice: once in
Visual mode and once in Collision mode.

### Single CGF/CGA

1. Open **File > Import > Aion CGF (.cgf)**.
2. Select an unpacked `.cgf` or `.cga` file.
3. Choose Visual or Collision mode.
4. Run the import.

## Import Modes

- **Visual**: rich scene import with terrain, textures, liquid surface preview,
  static lights, mission placeables, CGA entities, texture sequences, and shader
  UV scroll where supported.
- **Collision**: terrain heightfield and collision geometry only. Visual and
  dynamic preview options are ignored in this mode.

## Experimental Features

- Particle Effects preview is experimental, heavy, and disabled by default.
- CGA controller animation is experimental and currently supports only decoded
  rotation controller cases.

## Legal / Data Note

This repository does not include Aion game client assets. You must provide your
own local client files.

## License

MIT License. See `LICENSE`.
