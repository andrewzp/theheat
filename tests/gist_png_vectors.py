"""Invented cross-build image vectors for every native Gist family (no real weather).

GOLDEN maps each case to (decoded RGB SHA256, canonical PNG SHA256, PNG bytes). The
RGB digests equal the .46 renderer's decoded pixels (8c064ee, Pillow 12.2.0, FreeType
2.14.3); canonical serialization changed only the compressed bytes. Any host with the
same Pillow/FreeType rasterization must reproduce every PNG digest exactly.
"""
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from tests.ghcn_graphic_helpers import graphic_bundles
from tests.gist_hazard_helpers import (MODIS_COORDINATES, MODIS_VALUES, SENDABLE_PM25, VARYING_PM25,
                                       VIIRS_CATEGORIES, modis_bundle, pm25_bundle, viirs_bundle)

DATELINE = [(-17.5, 179.4), (-16.8, -179.2)]


def _temperature(direction, tier):
    return lambda: story_bundle_snapshot(graphic_bundles(direction=direction, tier=tier)[-1])


CASES = {
    **{f"temperature-{d}-{t}": ("temperature", _temperature(d, t), False)
       for d in ("high", "low") for t in ("all_time", "monthly", "calendar")},
    "temperature-high-all_time-SYNTHETIC": ("temperature", _temperature("high", "all_time"), True),
    "pm25-sendable-varying": ("hazard", lambda: pm25_bundle(VARYING_PM25, **SENDABLE_PM25), False),
    "pm25-flat": ("hazard", lambda: pm25_bundle([150.0] * 24, **SENDABLE_PM25), False),
    "pm25-extreme-spike": ("hazard", lambda: pm25_bundle([100] * 23 + [2400], **SENDABLE_PM25), False),
    "pm25-default": ("hazard", lambda: pm25_bundle(), False),
    "pm25-varying-SYNTHETIC": ("hazard", lambda: pm25_bundle(VARYING_PM25), True),
    "modis-four": ("hazard", lambda: modis_bundle(MODIS_VALUES, coordinates=MODIS_COORDINATES), False),
    "modis-three-default": ("hazard", lambda: modis_bundle(), False),
    "modis-dateline": ("hazard", lambda: modis_bundle((500.1234, 125.75), coordinates=DATELINE), False),
    "modis-single-southern-SYNTHETIC": ("hazard", lambda: modis_bundle((812.5,), coordinates=[(-33.9, 151.2)]), True),
    "viirs-noaa20-four": ("hazard", lambda: viirs_bundle(MODIS_VALUES, categories=VIIRS_CATEGORIES,
                                                         coordinates=MODIS_COORDINATES), False),
    "viirs-noaa21-dateline": ("hazard", lambda: viirs_bundle((500.1234, 125.75), product="VIIRS_NOAA21_NRT",
                                                             categories=("nominal", "low"), coordinates=DATELINE), False),
    "viirs-three-default": ("hazard", lambda: viirs_bundle(), False),
}

GOLDEN = {
    "temperature-high-all_time": ("1a46dcc34ffc6dce3bb92abb1c44236326e946fabf9d671b0c237d93e07b2680",
        "14c3f9b5a035d7bac20fc10103ebef60da2144f0ac47b6ade37f248cc9b46869", 227168),
    "temperature-high-monthly": ("bc798c63354c2dd467adf16539a6efc121911990259e4ba0d5a7805daa6d2177",
        "0f996407703c32423d960e93529fe78fc12929a0d7d81a6166e1cf16603bd93c", 226277),
    "temperature-high-calendar": ("eb7101e4c8098348476c3193851f8e7dcc88774dc1671a3ae230ac91b726fb7e",
        "90f3b48fe2e1307ff6cd3146a2d2ba9141c2e78f9fd3bf13454207ed9b501bc0", 231745),
    "temperature-low-all_time": ("28a94cf0aa262684a5a833f2bb5e5166664d58547db5a559ec8585e3230e477a",
        "109bcbb3a88436d5769e0436822e3a5d1b563da51ff4061d4e17ce99ea27b38d", 228635),
    "temperature-low-monthly": ("e60e2f0c70c87e1bb13bdf5dcf58dca98fcf19baf9efd41edfad974f5f3c67ad",
        "d715116b7859a2351ecc14ca293be4c5ed46855e4ec9a64eae5815dee9d56a3f", 227744),
    "temperature-low-calendar": ("e382a1b1de02c6a23c34116ec09d7b204b3d6244063863d7d8221e19283192c6",
        "7c0a6a4a45064ed9ec1a36833bd1cc03ea105ad4c31252e97019b72d0aefdee0", 232445),
    "temperature-high-all_time-SYNTHETIC": ("fb88ce2b0255d5d30621cde0ecb339ce831d93c1d9e1c2f8f708bbe130395474",
        "2a030a20594baec945bd58e2a4fbe64d176d62c0d39b0e7f6ee49371772fa420", 231475),
    "pm25-sendable-varying": ("2f61d920649fca094fca7142c6a8c50bb1208bc9f18ae54f28f2dff30ce7192d",
        "2ff19b3b65ef5df6916f9c6f87e083f35bcf8f563c516fb7b900d1da8d2291e8", 226671),
    "pm25-flat": ("2c7b2264d459d9e8e177467a04763a0407b2ad1fa6adb112490cbe7bcd84be58",
        "2af76c5a26981dbe74d23d59914f166910e6520eea7ae7cf504b4c9017b3a406", 223150),
    "pm25-extreme-spike": ("52764cd4b199a0b311c8141ed5470b8e7808daf375dd686494a07758db6f99dd",
        "20a3e6ebc128a2cc52792ea8dfeae0d8f42b0a00511c9962fb1738946c29aade", 229196),
    "pm25-default": ("b8d36b4123e49b3d4578b6fd48aa84c453ebfc8898dbf34d3c6b249b03930914",
        "05342cfcced606c3e3605e2b8a006be3872a0db96045b6bdef1c8b147d958360", 230563),
    "pm25-varying-SYNTHETIC": ("d6cbb70adb4236d01424f86ccd268eab63b552d38bb7f186147e2b942299aa0a",
        "a91a626a6b366b39ac66c44dc1602fdb0cbc56e51b6644d0b5b97021fdd3895e", 239889),
    "modis-four": ("775edeec64dce264a156df317cbcd644c40dd5561ea354a4d324d98230d5b992",
        "6b5dc08fb4c2f28f3e5e73157d4ff42eab1ee3a93edbc3f8b51f6580f5cbfbc3", 222341),
    "modis-three-default": ("8543f4db9709b40d3a676673c0e86027744d126a42f15f612dc305347eb278ed",
        "3dbde8b233de9d82d73bb5c772b1a1e08abbe9d46fc15282ea03796239b22f85", 220950),
    "modis-dateline": ("34bf7d04c6305c3ca49d14311e9eb4242d2a0b2564566d2779de358c8aec3b74",
        "646f206392b262fcd5f1669ab76d18f3b6d435fdd1c04a85cf50b41c5e3a7aeb", 218223),
    "modis-single-southern-SYNTHETIC": ("0a584dbd16d8529950ffa448ceaaf5e64ab70bff55733890bddd05cd73cb4f43",
        "0afacb9c6380c36d36a9c14ad2e2bdf656ecc3e55633b6c0e522a59cbfc70429", 214590),
    "viirs-noaa20-four": ("22b36c309ceb5ce09ce9443245f67415defe052a1b7c8e99b242e4f7ac80647f",
        "894f541d97bb6ff27c651d6e34ea04027cb1c45431542f7a5eebaa93611dc721", 246932),
    "viirs-noaa21-dateline": ("8fe3936e5d31af4c7bee9d9e1a30787ae64682116df9bdebc58b4a4de3d3e3b7",
        "8aa3ef99dcc306cb0574cf34fb0f1728234fad67399b0b0dc920e093c038862a", 237174),
    "viirs-three-default": ("dd5357bc8d5e28e563158834f38d60c3e82259cb9f81ecbb73f81609bb7c7569",
        "96cfcffe6403fe22224d84baf549f16bb35d99c5e7dd6d7a07bc705ed5669b92", 243265),
}
