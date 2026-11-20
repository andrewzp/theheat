"""Create invented NetCDF4 bytes in a child process, separate from h5py readers."""
from datetime import UTC, date, datetime
from pathlib import Path
import sys


def create(path: Path, day: date):
    import netCDF4
    import numpy as np

    assert not path.exists()
    with netCDF4.Dataset(path, "w", format="NETCDF4") as handle:
        for name, size in (("time", 1), ("lon", 3600), ("lat", 1800)):
            handle.createDimension(name, size)
        values = handle.createVariable("precipitation", "f4", ("time", "lon", "lat"),
                                       fill_value=-9999, zlib=True, chunksizes=(1, 100, 100))
        values.units = "mm/day"
        values.scale_factor, values.add_offset = np.float32(1), np.float32(0)
        values.set_auto_maskandscale(False)
        values[:] = np.float32(0)
        values[0, 1299, 799] = np.float32(190.5)
        counts = handle.createVariable("precipitation_cnt", "i1", ("time", "lon", "lat"),
                                       fill_value=-1, zlib=True, chunksizes=(1, 100, 100))
        counts[:] = np.int8(48)
        for name, size, start, units in (("lon", 3600, -179.95, "degrees_east"),
                                         ("lat", 1800, -89.95, "degrees_north")):
            axis = handle.createVariable(name, "f4", (name,), fill_value=-9999)
            axis.units = units
            axis[:] = (start + np.arange(size) * .1).astype("f4")
        time = handle.createVariable("time", "f8", ("time",))
        time.units, time.calendar = "seconds since 1970-01-01 00:00:00 UTC", "gregorian"
        time[:] = datetime.combine(day, datetime.min.time(), UTC).timestamp()


if __name__ == "__main__":
    output, source_day = sys.argv[1:]
    create(Path(output), date.fromisoformat(source_day))
