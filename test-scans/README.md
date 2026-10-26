# Scanned sheets for testing the reader

Put handwritten, scanned trip sheets here as PDFs (200-300 dpi, grayscale is fine). They are only
used to test and tune the reader - nothing in this folder is served by the app or read at startup.

    test-scans/
      2026-10-21-aw07.pdf      one day, one or more buses

Useful to include, if you have them:

- a sheet filled by a driver with ordinary handwriting, and one filled in a hurry;
- a day where a run was cut short or did not run, so the Ran / Cut / Not ticks and a reason number appear;
- a sheet where another bus ran the schedule, so the bus-change block is filled;
- a page that was scanned slightly skewed, which is what most real scans look like.

Alongside each PDF, a plain text file of what the sheet actually says lets the reader be scored
rather than eyeballed, e.g. `2026-10-21-aw07.txt`:

    run 1  departed 09:20  start_soc 100  start_odo 19427  arrived 09:30  end_soc 97  end_odo 19430
    run 2  departed 09:35  start_soc 97   start_odo 19430  arrived 11:44  end_soc 59  end_odo 19503

That file is optional - without it the reader can still be run, but accuracy has to be judged by eye.
