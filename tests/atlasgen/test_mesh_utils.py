from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from brainglobe_atlasapi.atlas_generation.mesh_utils import (
    Region,
    create_region_mesh,
    extract_mesh_from_mask,
)
from brainglobe_atlasapi.structure_tree_util import get_structures_tree


@pytest.mark.parametrize("label", [True, False, "True"])
def test_region_has_label(label):
    """Test if label is added correctly as class instance variable.

    Label is added without explicitly assinging it to has_label
    (which would be `Region(has_label=label)`), as this reflects what
    happens during the atlas generation.
    """
    region = Region(label)
    assert region.has_label == label


@pytest.fixture
def region_mesh_args(structures, tmp_path, request):
    """Fixture for creating arguments for `create_region_mesh`.

    `label_id` can be passed using indirect parametrization.
    """
    label_id = request.param
    meshes_dir_path = tmp_path
    tree = get_structures_tree(structures)
    node = tree.nodes[label_id]
    smoothed_annotations = np.load(
        Path(__file__).parent / "dummy_data" / "smoothed_annotations.npy"
    )
    labels = np.unique(smoothed_annotations).astype(np.int_)
    root_id = 999
    closing_n_iters = 10
    decimate_fraction = 0.6
    smooth = True
    return (
        meshes_dir_path,  # 0
        node,  # 1
        tree,  # 2
        labels,  # 3
        smoothed_annotations,  # 4
        root_id,  # 5
        closing_n_iters,  # 6
        decimate_fraction,  # 7
        smooth,  # 8
    )


@pytest.mark.parametrize(
    "region_mesh_args, test_case, expected_captured_out",
    [
        pytest.param(5, "empty_mask", "Empty mask for", id="empty mask"),
        pytest.param(5, "no_match", "No labels found for", id="no label"),
    ],
    indirect=["region_mesh_args"],
)
def test_create_region_mesh_fail(
    region_mesh_args, capsys, test_case, expected_captured_out
):
    """Test create_region_mesh handling of label mismatch / empty mask.

    The test expects no mesh_files to be created and checks whether the right
    message is printed.
    """

    if test_case == "empty_mask":
        smoothed_annotations = region_mesh_args[4]
        smoothed_annotations[:] = 0

    elif test_case == "no_match":
        labels = region_mesh_args[3]
        labels[labels == 5] = 123

    create_region_mesh(region_mesh_args)
    captured_out = capsys.readouterr().out
    mesh_files = list(region_mesh_args[0].iterdir())
    assert len(mesh_files) == 0
    assert expected_captured_out in captured_out


@pytest.mark.parametrize(
    "region_mesh_args",
    [
        pytest.param(5),
        pytest.param(999, id="root_id (999)"),
    ],
    indirect=True,
)
def test_create_region_mesh(region_mesh_args):
    """Test region mesh creation with specific label_id."""
    create_region_mesh(region_mesh_args)
    mesh_files = list(region_mesh_args[0].iterdir())
    assert len(mesh_files) == 1
    assert mesh_files[0].suffix == ".obj"


@pytest.fixture
def mesh_from_mask():
    """Fixture with volume and default parameters for `mesh_from_mask`.

    The `volume` is a 100 unit cube of zeros with a centered 50 unit cube of
    ones in the middle.
    """
    volume = np.zeros((100, 100, 100), dtype=int)
    volume[24:75, 24:75, 24:75] = 1

    return {
        "volume": volume,
        "obj_filepath": None,
        "threshold": 0.5,
        "smooth": False,
        "mcubes_smooth": False,
        "closing_n_iters": 8,  # default
        "decimate_fraction": 0.6,
        "use_marching_cubes": False,
        "extract_largest": False,
    }


@pytest.mark.parametrize("obj_filepath_is_str", [True, False])
def test_extract_mesh_from_mask_object_filepath_str(
    mesh_from_mask, tmp_path, obj_filepath_is_str
):
    """Test conversion to path when `obj_filepath` is a string."""
    obj_filepath = tmp_path / "mesh"
    if obj_filepath_is_str:
        obj_filepath = str(obj_filepath)
    mesh_from_mask.update({"obj_filepath": obj_filepath})

    with patch(
        "brainglobe_atlasapi.atlas_generation.mesh_utils.Path"
    ) as mock_path:
        extract_mesh_from_mask(**mesh_from_mask)
        if obj_filepath_is_str:
            mock_path.assert_called_once_with(obj_filepath)
        else:
            mock_path.assert_not_called()


def test_extract_mesh_from_mask_none_existing_parent(mesh_from_mask, tmp_path):
    """Test handling of obj filepath with missing parent"""
    obj_filepath = tmp_path / "non_existing_parent" / "mesh"
    mesh_from_mask.update({"obj_filepath": obj_filepath})
    match = "The folder where the .obj file is to be saved doesn't exist"
    with pytest.raises(FileExistsError, match=match):
        extract_mesh_from_mask(**mesh_from_mask)


def test_extract_mesh_from_mask_defaults(mesh_from_mask):
    """Test extract_mesh_from_mask with defaults"""
    mesh = extract_mesh_from_mask(**mesh_from_mask)
    assert mesh.contains([50, 50, 50]) is True
    assert mesh.contains([2, 2, 2]) is False


def test_extract_mesh_from_mask_ValueError(mesh_from_mask):
    """Test ValueError for non-binary volume in `extract_mesh_from_mask`."""
    volume = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
    mesh_from_mask.update({"volume": volume})
    with pytest.raises(ValueError, match="volume should be a binary mask"):
        extract_mesh_from_mask(**mesh_from_mask)


@pytest.mark.parametrize("mcubes_smooth", [False, True])
def test_extract_mesh_from_mask_marching_cubes(
    mcubes_smooth, mesh_from_mask, capsys
):
    """Test mesh_from_mask using marching cubes with/without mcubes_smooth."""
    mesh_from_mask.update({"use_marching_cubes": True})
    mesh_from_mask.update({"mcubes_smooth": mcubes_smooth})
    extract_mesh_from_mask(**mesh_from_mask)
    captured = capsys.readouterr()
    assert captured.out.startswith(
        "The marching cubes algorithm might be rotated "
    )


@pytest.mark.parametrize("extract_largest", [False, True])
def test_extract_largest_mesh_from_mask(extract_largest, mesh_from_mask):
    """Test `extract_largest` during mesh from mask extraction.

    Tests mesh volume when extract_largest parameter set to True / False.

    `expected_mesh_largest_true` is created using the volume mask from the
    `mesh_from_mask` fixture, which contains one large region.

    `expected_mesh_largest_false` is created using a volume mask containing
    the original large region and an additional smaller region (with default
    extract_largest = False)

    `mesh` is created using the volume mask with both regions, setting
    extract_largest to True / False.

    The assertions check that the mesh area matches the expected values based
    on the `extract_largest` parameter.
    """

    # using the origingal volume containing only the large region
    expected_mesh_largest_true = extract_mesh_from_mask(**mesh_from_mask)

    volume = np.zeros((100, 100, 100), dtype=int)
    volume[24:75, 24:75, 24:75] = 1  # Large region
    volume[4:10, 4:10, 4:10] = 1  # Small region

    mesh_from_mask.update({"volume": volume})
    expected_mesh_largest_false = extract_mesh_from_mask(**mesh_from_mask)

    # parametrize extract_largest to False / True
    mesh_from_mask.update({"extract_largest": extract_largest})
    mesh = extract_mesh_from_mask(**mesh_from_mask)

    if extract_largest is True:
        assert np.isclose(mesh.area(), expected_mesh_largest_true.area())
    else:
        assert np.isclose(
            mesh.area(),
            expected_mesh_largest_false.area(),
        )


@pytest.mark.parametrize("zeros_ones", [0, 1])
def test_mesh_from_mask_only_zeros_or_ones(zeros_ones, mesh_from_mask):
    """Test mesh extraction from masks containing only zeros or only ones."""
    volume = np.full((100, 100, 100), zeros_ones, dtype=int)
    mesh_from_mask.update({"volume": volume})
    mesh = extract_mesh_from_mask(**mesh_from_mask)
    if zeros_ones == 0:
        assert np.isclose(mesh.area(), 0)
    else:
        assert mesh.area() > 0
