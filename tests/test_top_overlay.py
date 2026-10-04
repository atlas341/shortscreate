from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.processing import processor
from app.processing.top_overlay import (
    top_overlay_base_filters,
    top_overlay_filters,
)


class TopOverlayFiltersTest(unittest.TestCase):
    def test_overlay_height_does_not_change_base_video_filters(self) -> None:
        base_filters, size = top_overlay_base_filters(
            background_index=1,
            output_label="[base]",
            mirror=False,
            fps=30,
        )

        short_overlay = top_overlay_filters(
            video_label="[base]",
            overlay_index=2,
            output_label="[short]",
            fps=30,
            height=300,
        )
        tall_overlay = top_overlay_filters(
            video_label="[base]",
            overlay_index=2,
            output_label="[tall]",
            fps=30,
            height=600,
        )

        self.assertEqual(size, (1080, 1920))
        self.assertIn("scale=1080:1920:", ";".join(base_filters))
        self.assertEqual(
            short_overlay[0].replace("1080:300", "1080:<height>"),
            tall_overlay[0].replace("1080:600", "1080:<height>"),
        )
        self.assertIn("scale=1080:300:", short_overlay[0])
        self.assertIn("scale=1080:600:", tall_overlay[0])
        self.assertEqual(
            short_overlay[1],
            "[base][topvideo]overlay=x=0:y=0:shortest=1[short]",
        )
        self.assertEqual(
            tall_overlay[1],
            "[base][topvideo]overlay=x=0:y=0:shortest=1[tall]",
        )


class TopOverlayProcessorTest(unittest.TestCase):
    def test_overlay_is_last_video_layer_after_subtitles_banner_and_outro(self) -> None:
        with TemporaryDirectory(dir=processor.settings.base_dir) as temp_dir:
            root = Path(temp_dir)
            input_file = root / "source.mp4"
            input_file.touch()
            work_dir = root / "work"
            ass_file = work_dir / "subtitles.ass"

            patches = [
                patch.object(processor, "get_video_size", return_value=(1920, 1080)),
                patch.object(processor, "get_duration", return_value=12.0),
                patch.object(processor, "has_audio", return_value=False),
                patch.object(processor, "get_frame_rate", return_value="30"),
                patch.object(
                    processor,
                    "background_input_arguments",
                    return_value=(
                        ["-i", "background.mp4"],
                        Path("background.mp4"),
                    ),
                ),
                patch.object(
                    processor,
                    "pick_overlay_video",
                    return_value=Path("overlay.mp4"),
                ),
                patch.object(
                    processor,
                    "overlay_input_arguments",
                    return_value=["-i", "overlay.mp4"],
                ),
                patch.object(processor, "srt_to_ass", return_value=ass_file),
                patch.object(processor, "fonts_dir_option", return_value=""),
                patch.object(
                    processor,
                    "get_banner_by_name",
                    return_value=Path("banner.png"),
                ),
                patch.object(
                    processor,
                    "banner_input_arguments",
                    return_value=["-i", "banner.png"],
                ),
                patch.object(
                    processor,
                    "banner_filters",
                    return_value=(["[subbed]banner[bannered]"], (1920, 1080)),
                ),
                patch.object(
                    processor,
                    "find_outro_image",
                    return_value=Path("outro.png"),
                ),
                patch.object(
                    processor,
                    "outro_input_arguments",
                    return_value=["-i", "outro.png"],
                ),
                patch.object(
                    processor,
                    "outro_filters",
                    return_value=["[bannered]outro[with_outro]"],
                ),
                patch.object(
                    processor,
                    "top_overlay_filters",
                    side_effect=lambda video_label, overlay_index, output_label, fps: [
                        f"[{overlay_index}:v]scale=1080:300[topvideo]",
                        f"{video_label}[topvideo]overlay=x=0:y=0:shortest=1{output_label}",
                    ],
                ),
                patch.object(processor, "pick_music", return_value=(None, 0.0)),
                patch.object(
                    processor,
                    "ensure_output",
                    return_value=root / "work" / "result.mp4",
                ),
                patch.object(processor, "file_size_mb", return_value=1.0),
            ]

            with ExitStack() as stack:
                for test_patch in patches:
                    stack.enter_context(test_patch)

                run_ffmpeg = stack.enter_context(patch.object(processor, "run_ffmpeg"))
                processor.process_video(
                    input_file=input_file,
                    work_dir=work_dir,
                    options=processor.ProcessingOptions(
                        mode="top_overlay",
                        mirror=False,
                        subtitles_file=root / "subtitles.srt",
                        banner_name="banner.png",
                        outro=True,
                    ),
                )

            arguments = run_ffmpeg.call_args.args[0]
            filter_graph = arguments[arguments.index("-filter_complex") + 1]
            expected_order = [
                "[uniq]ass=filename=",
                "[subbed]banner[bannered]",
                "[bannered]outro[with_outro]",
                "[2:v]scale=1080:300[topvideo]",
                "[with_outro][topvideo]overlay=x=0:y=0:shortest=1[top_overlayed]",
                "[top_overlayed]format=yuv420p[vout]",
            ]
            positions = [filter_graph.index(part) for part in expected_order]

            self.assertEqual(positions, sorted(positions))
            self.assertEqual(arguments[arguments.index("-map") + 1], "[vout]")


if __name__ == "__main__":
    unittest.main()
