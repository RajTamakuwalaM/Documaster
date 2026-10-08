# filename: branding_logic.py
from PIL import Image, ImageDraw, ImageFont
import os

def apply_branding_to_image(img_path, save_path, doc_branding_map, font_config, margin):
    try:
        with Image.open(img_path) as img:
            original_mode = img.mode
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            dpi = img.info.get('dpi', (300, 300))
            dpi_x = dpi[0] if isinstance(dpi, tuple) else 300
            
            pt_size = font_config.get("size", 10)
            
            # Extract Both Offsets
            y_off_pt = font_config.get("y_offset", 0) 
            x_off_pt = font_config.get("x_offset", 0) 
            
            px_size = int(pt_size * (dpi_x / 65)) 
            margin_px = int(margin * (dpi_x / 65))
            
            # Convert offsets to pixels
            y_off_px = int(y_off_pt * (dpi_x / 65))
            x_off_px = int(x_off_pt * (dpi_x / 65))

            font_name = font_config.get("family", "arial.ttf")
            try:
                font = ImageFont.truetype(font_name, px_size)
            except Exception:
                try:
                    font = ImageFont.truetype(f"C:\\Windows\\Fonts\\{font_name}", px_size)
                except Exception:
                    font = ImageFont.load_default()

            width, height = img.size
            
            # ==================================================
            # Y-AXIS: ADD WHITE MARGIN AT THE BOTTOM
            # ==================================================
            has_bottom_text = any(pos in ["BL", "BC", "BR"] for pos in doc_branding_map if doc_branding_map[pos].get("text"))
            
            if y_off_px > 0 and has_bottom_text:
                new_height = height + y_off_px
                new_img = Image.new("RGB", (width, new_height), "white")
                new_img.paste(img, (0, 0))
                img = new_img
                height = new_height 
            # ==================================================
            
            draw = ImageDraw.Draw(img)
            
            for pos, config in doc_branding_map.items():
                text = str(config.get("text", "")).strip()
                if not text: continue
                
                color = config.get("color", "black")
                
                try:
                    bbox = draw.textbbox((0, 0), text, font=font)
                    l_pad = bbox[0]
                    t_pad = bbox[1]
                    r_pad = bbox[2]
                    b_pad = bbox[3]
                except:
                    try:
                        tw, th = draw.textsize(text, font=font)
                        l_pad, t_pad = 0, 0
                        r_pad, b_pad = tw, th
                    except:
                        l_pad, t_pad = 0, 0
                        r_pad, b_pad = len(text) * (px_size // 2), px_size

                tw = r_pad - l_pad
                x, y = 0, 0
                
                if pos == "TL":
                    x = margin_px - l_pad
                    y = margin_px - t_pad
                elif pos == "TC":
                    x = (width // 2) - (tw // 2) - l_pad
                    y = margin_px - t_pad
                elif pos == "TR":
                    x = width - margin_px - r_pad
                    y = margin_px - t_pad
                elif pos == "BL":
                    x = margin_px - l_pad
                    y = height - margin_px - b_pad
                elif pos == "BC":
                    x = (width // 2) - (tw // 2) - l_pad
                    y = height - margin_px - b_pad
                elif pos == "BR":
                    x = width - margin_px - r_pad
                    y = height - margin_px - b_pad
                
                # ==================================================
                # X-AXIS: SMART HORIZONTAL SHIFT 
                # Positive value shifts text INWARDS (Center ki taraf)
                # ==================================================
                if pos in ["TL", "BL"]:
                    x += x_off_px     # Left items shift Right
                elif pos in ["TR", "BR"]:
                    x -= x_off_px     # Right items shift Left
                elif pos in ["TC", "BC"]:
                    x += x_off_px     # Center items shift Right
                # ==================================================
                    
                draw.text((x, y), text, font=font, fill=color)

            # --- FIX: Check if user applied any custom colors ---
            has_color = False
            for pos, config in doc_branding_map.items():
                c = str(config.get("color", "#000000")).lower()
                # Agar black/white ke alawa koi rang hai, toh B&W mode bypass karenge
                if c not in ["black", "#000000", "white", "#ffffff"]:
                    has_color = True

            ext = os.path.splitext(save_path)[1].lower()

            # --- NEW FIX: Force JPEG for Colored Images (Relativity/LAW Compatibility) ---
            if ext in [".tif", ".tiff"] and has_color:
                save_path = os.path.splitext(save_path)[0] + ".jpg"
                ext = ".jpg"
            # -----------------------------------------------------------------------------

            if ext in [".jpg", ".jpeg"]:
                # Save as High-Quality JPEG
                img.save(save_path, format="JPEG", quality=95, dpi=dpi)
            elif ext in [".tif", ".tiff"]:
                # Save as 1-Bit B&W TIFF
                if original_mode in ["1", "L", "I;16"]:                    
                    from PIL import ImageOps
                    img_inverted = ImageOps.invert(img)
                    img_1bit = img_inverted.convert("1", dither=Image.NONE)
                    img_1bit.save(save_path, compression="tiff_ccitt", dpi=dpi, photometric_interpretation=0)
                else:
                    img.save(save_path, compression="tiff_lzw", dpi=dpi)
            else:
                img.save(save_path, dpi=dpi)
            
            return True

    except Exception as e:
        try:
            out_dir = os.path.dirname(save_path)
            with open(os.path.join(out_dir, "BRANDING_CRASH_LOG.txt"), "a", encoding="utf-8") as f:
                f.write(f"Error on {os.path.basename(img_path)}: {str(e)}\n")
        except: pass
        return False