from pathlib import Path
import importlib.util


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "remove_image_number_prefix.py"
spec = importlib.util.spec_from_file_location("remove_image_number_prefix", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def test_stripped_name():
    assert mod.stripped_name("8571_reindeer_antlers.png") == "reindeer_antlers.png"
    assert mod.stripped_name("12_a_b.webp") == "a_b.webp"
    assert mod.stripped_name("reindeer_antlers.png") is None


def test_build_dedupe_plan_collapses_same_object_to_one_name(tmp_path):
    image_dir = tmp_path / "items"
    image_dir.mkdir()
    (image_dir / "1_same.png").write_bytes(b"a")
    (image_dir / "2_same.png").write_bytes(b"b")
    (image_dir / "3_same.png").write_bytes(b"c")

    renames, removals = mod.build_dedupe_plan(image_dir)

    assert [(src.name, dst.name) for src, dst in renames] == [("1_same.png", "same.png")]
    assert [(src.name, dst.name) for src, dst in removals] == [
        ("2_same.png", "same.png"),
        ("3_same.png", "same.png"),
    ]


def test_existing_clean_name_becomes_canonical(tmp_path):
    image_dir = tmp_path / "items"
    image_dir.mkdir()
    (image_dir / "same.png").write_bytes(b"existing")
    (image_dir / "1_same.png").write_bytes(b"a")
    (image_dir / "2_same.png").write_bytes(b"b")

    renames, removals = mod.build_dedupe_plan(image_dir)

    assert renames == []
    assert [(src.name, dst.name) for src, dst in removals] == [
        ("1_same.png", "same.png"),
        ("2_same.png", "same.png"),
    ]


def test_rename_directory_keeps_only_one_canonical_file(tmp_path):
    image_dir = tmp_path / "items"
    image_dir.mkdir()
    (image_dir / "1_hat.png").write_bytes(b"first")
    (image_dir / "2_hat.png").write_bytes(b"second")

    renamed, removed, replacements = mod.rename_directory(image_dir, dry_run=False)

    assert renamed == 1
    assert removed == 1
    assert (image_dir / "hat.png").read_bytes() == b"first"
    assert not (image_dir / "1_hat.png").exists()
    assert not (image_dir / "2_hat.png").exists()
    assert list(image_dir.iterdir()) == [image_dir / "hat.png"]
    assert replacements[(image_dir / "1_hat.png").as_posix()] == (image_dir / "hat.png").as_posix()
    assert replacements[(image_dir / "2_hat.png").as_posix()] == (image_dir / "hat.png").as_posix()


def test_lowest_numeric_prefix_is_kept(tmp_path):
    image_dir = tmp_path / "items"
    image_dir.mkdir()
    (image_dir / "10_hat.png").write_bytes(b"ten")
    (image_dir / "2_hat.png").write_bytes(b"two")

    renamed, removed, _ = mod.rename_directory(image_dir, dry_run=False)

    assert renamed == 1
    assert removed == 1
    assert (image_dir / "hat.png").read_bytes() == b"two"


def test_update_csv_path(tmp_path):
    path = tmp_path / "item_images.csv"
    path.write_text(
        "item_id,local_path\n1,images/items/1_hat.png\n2,images/items/2_hat.png\n",
        encoding="utf-8",
    )
    changed = mod.update_csv(
        path,
        {
            "images/items/1_hat.png": "images/items/hat.png",
            "images/items/2_hat.png": "images/items/hat.png",
        },
        {"local_path"},
        dry_run=False,
    )
    text = path.read_text(encoding="utf-8-sig")
    assert changed == 2
    assert text.count("images/items/hat.png") == 2


def test_canonical_image_name_removes_trailing_number():
    assert mod.canonical_image_name("hat_2.png") == "hat.png"
    assert mod.canonical_image_name("hat_99.webp") == "hat.webp"
    assert mod.canonical_image_name("8571_hat_2.png") == "hat.png"
    assert mod.canonical_image_name("hat.png") == "hat.png"


def test_trailing_number_files_are_deduplicated(tmp_path):
    image_dir = tmp_path / "items"
    image_dir.mkdir()
    (image_dir / "hat.png").write_bytes(b"canonical")
    (image_dir / "hat_2.png").write_bytes(b"duplicate-2")
    (image_dir / "hat_3.png").write_bytes(b"duplicate-3")

    renamed, removed, replacements = mod.rename_directory(image_dir, dry_run=False)

    assert renamed == 0
    assert removed == 2
    assert (image_dir / "hat.png").read_bytes() == b"canonical"
    assert not (image_dir / "hat_2.png").exists()
    assert not (image_dir / "hat_3.png").exists()
    assert replacements[(image_dir / "hat_2.png").as_posix()] == (image_dir / "hat.png").as_posix()
    assert replacements[(image_dir / "hat_3.png").as_posix()] == (image_dir / "hat.png").as_posix()


def test_mixed_prefix_and_tail_aliases_collapse(tmp_path):
    image_dir = tmp_path / "items"
    image_dir.mkdir()
    (image_dir / "5_hat_2.png").write_bytes(b"five")
    (image_dir / "hat_3.png").write_bytes(b"three")

    renamed, removed, _ = mod.rename_directory(image_dir, dry_run=False)

    assert renamed == 1
    assert removed == 1
    assert (image_dir / "hat.png").exists()
    assert len(list(image_dir.iterdir())) == 1
