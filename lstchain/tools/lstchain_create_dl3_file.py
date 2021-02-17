"""
Create DL3 FITS file from given data DL2 file,
selection cuts and/or IRF FITS files

Simple usage with argument aliases and default config file for selection cuts:

lstchain_create_irf_files
    --d /path/to/DL2_data_file.h5
    --o /path/to/DL3/file/
    --add_irf True
    --irf /path/to/irf.fits.gz
    --source_name Crab
"""

import os

from ctapipe.core import Tool, traits, Provenance
from lstchain.io import read_data_dl2_to_QTable, read_configuration_file
from lstchain.reco.utils import filter_events
from lstchain.paths import run_info_from_filename
from lstchain.irf import create_event_list

from pyirf.utils import calculate_source_fov_offset

from astropy.io import fits
import astropy.units as u

__all__ = ["DataReductionFITSWriter"]


class DataReductionFITSWriter(Tool):
    name = "DataReductionFITSWriter"
    description = __doc__

    input_dl2 = traits.Path(
        help="Input data DL2 file", exists=True, directory_ok=False, file_ok=True
    ).tag(config=True)

    output_dl3_path = traits.Path(
        help="DL3 output filedir", directory_ok=True, file_ok=False
    ).tag(config=True)

    add_irf = traits.Bool(
        help="True for adding IRF fits file to the DL3 file",
        default_value=True,
    ).tag(config=True)

    input_irf = traits.Path(
        help="Compressed FITS file of IRFs",
        exists=True,
        directory_ok=False,
        file_ok=True,
    ).tag(config=True)

    config_file = traits.Path(
        help="Config file for selection cuts",
        directory_ok=False,
        file_ok=True,
    ).tag(config=True)

    source_name = traits.Unicode(help="Name of Source").tag(config=True)

    aliases = {
        "input_dl2": "DataReductionFITSWriter.input_dl2",
        "d": "DataReductionFITSWriter.input_dl2",
        "output_dl3_path": "DataReductionFITSWriter.output_dl3_path",
        "o": "DataReductionFITSWriter.output_dl3_path",
        "add_irf": "DataReductionFITSWriter.add_irf",
        "input_irf": "DataReductionFITSWriter.input_irf",
        "irf": "DataReductionFITSWriter.input_irf",
        "config_file": "DataReductionFITSWriter.config_file",
        "conf": "DataReductionFITSWriter.config_file",
        "source_name": "DataReductionFITSWriter.source_name",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.data = None
        self.filename_dl3 = None
        self.run_number = None
        self.cuts = None
        self.events = None
        self.gti = None
        self.pointing = None
        self.aeff2d = None
        self.edisp2d = None
        self.bkg2d = None
        # self.psf = None
        self.hdulist = None
        self.output_file = None

    def setup(self):
        if self.config_file is None:
            self.cuts = read_configuration_file(
                os.path.join(
                    os.path.dirname(__file__), "../data/data_selection_cuts.json"
                )
            )
        else:
            self.cuts = read_configuration_file(self.config_file)

        filename_dl2 = str(self.input_dl2).split("/")[-1]
        self.filename_dl3 = filename_dl2.replace("dl2", "dl3")
        self.filename_dl3 = self.filename_dl3.replace("h5", "fits")

        self.data = read_data_dl2_to_QTable(str(self.input_dl2))

        self.run_number = run_info_from_filename(self.input_dl2)[1]

    def start(self):
        self.data["reco_source_fov_offset"] = calculate_source_fov_offset(
            self.data, prefix="reco"
        )

        self.data = filter_events(self.data, self.cuts["events_filters"])

        # Separate cuts for angular separations, for now. Will be included later in filter_events
        self.data = self.data[
            self.data["gh_score"] > self.cuts["fixed_cuts"]["gh_score"][0]
        ]

        self.data = self.data[
            self.data["reco_source_fov_offset"]
            < u.Quantity(**self.cuts["fixed_cuts"]["source_fov_offset"])
        ]
        self.log.info("Generating event list")
        self.events, self.gti, self.pointing = create_event_list(
            data=self.data, run_number=self.run_number, source_name=self.source_name
        )

        if self.add_irf:
            irf = fits.open(self.input_irf)
            self.aeff2d = irf["EFFECTIVE AREA"]
            self.edisp2d = irf["ENERGY DISPERSION"]

            self.log.info("Adding IRF HDUs")
            self.hdulist = fits.HDUList(
                [
                    fits.PrimaryHDU(),
                    self.events,
                    self.gti,
                    self.pointing,
                    self.aeff2d,
                    self.edisp2d,
                ]
            )
            if len(irf) > 3:
                self.bkg2d = irf["BACKGROUND"]
                # self.psf = irf['PSF']
                self.hdulist.append(self.bkg2d)
                # self.hdulist.append(self.psf)

        else:
            self.hdulist = fits.HDUList(
                [fits.PrimaryHDU(), self.events, self.gti, self.pointing]
            )

    def finish(self):
        self.output_file = self.output_dl3_path / self.filename_dl3
        if self.output_file.exists():
            self.log.info(f"{self.output_file} exists, will be overwritten")

        self.hdulist.writeto(self.output_file, overwrite=True)

        Provenance().add_output_file(self.output_file)


def main():
    tool = DataReductionFITSWriter()
    tool.run()


if __name__ == "__main__":
    main()