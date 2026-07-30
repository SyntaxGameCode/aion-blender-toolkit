# Aion Blender Toolkit

![Version](https://img.shields.io/badge/version-0.4.32-blue)
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
- Full level imports report the current stage and CGF template progress.

## Installation

1. Download the release zip, for example `blender_aion_importer-0.4.32.zip`.
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
   - **Collision** imports terrain heightfield, collision CGF geometry, and
     collision geometry from placed CGA entities.

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
- **Collision**: terrain heightfield plus collision geometry from CGF and
  placed CGA entities. Visual materials, animation, and dynamic preview layers
  are ignored in this mode.

## Experimental Features

- Particle Effects preview is experimental, heavy, and disabled by default.
- CGA controller animation is experimental and currently supports only decoded
  rotation controller cases.

## Known Limitations

- Interactive cancellation is not implemented yet. Large full-level imports can
  still be slow or memory intensive.
- Particle `.prt` blend, size, orientation, and lifetime semantics are not fully
  decoded.
- CGA loop/cyclic semantics are unknown.
- Scale/pulse controllers are not fully supported, including cases such as
  `Na_D_gourdlotus_04d.cga`.
- Skeletal, CAF, CHR, and skinned animation are not supported.
- The addon requires original local client files. Game client assets are not
  included in this repository.

## Legal / Data Note

This repository does not include Aion game client assets. You must provide your
own local client files.

## License

MIT License. See `LICENSE`.
