# © 2020 James R. Barlow: github.com/jbarlow83
#
# This file is part of OCRmyPDF.
#
# OCRmyPDF is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OCRmyPDF is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with OCRmyPDF.  If not, see <http://www.gnu.org/licenses/>.

import logging
import logging.handlers
import multiprocessing
import os
import signal
import sys
import threading
from multiprocessing import Pool as ProcessPool
from multiprocessing.dummy import Pool as ThreadPool
from pathlib import Path

from tqdm import tqdm


def log_listener(queue):
    """Listen to the worker processes and forward the messages to logging

    For simplicity this is a thread rather than a process. Only one process
    should actually write to sys.stderr or whatever we're using, so if this is
    made into a process the main application needs to be directed to it.

    See https://docs.python.org/3/howto/logging-cookbook.html#logging-to-a-single-file-from-multiple-processes
    """

    while True:
        try:
            record = queue.get()
            if record is None:
                break
            logger = logging.getLogger(record.name)
            logger.handle(record)
        except Exception:
            import traceback

            print("Logging problem", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)


def exec_progress_pool(
    *,
    use_threads,
    max_workers,
    tqdm_kwargs,
    task_initializer=None,
    task_initargs=None,
    task=None,
    task_arguments=None,
    task_finished=None,
):
    log_queue = multiprocessing.Queue(-1)
    listener = threading.Thread(target=log_listener, args=(log_queue,))

    if use_threads:
        pool_class = ThreadPool
    else:
        pool_class = ProcessPool
    listener.start()

    with tqdm(**tqdm_kwargs) as pbar:
        pool = pool_class(
            processes=max_workers,
            initializer=task_initializer,
            initargs=(log_queue, *task_initargs),
        )
        try:
            results = pool.imap_unordered(task, task_arguments)
            while True:
                try:
                    result = results.next()
                    task_finished(result, pbar)
                except StopIteration:
                    break
        except KeyboardInterrupt:
            # Terminate pool so we exit instantly
            pool.terminate()
            # Don't try listener.join() here, will deadlock
            raise
        except Exception:
            if not os.environ.get("PYTEST_CURRENT_TEST", ""):
                # Unless inside pytest, exit immediately because no one wants
                # to wait for child processes to finalize results that will be
                # thrown away. Inside pytest, we want child processes to exit
                # cleanly so that they output an error messages or coverage data
                # we need from them.
                pool.terminate()
            raise
        finally:
            # Terminate log listener
            log_queue.put_nowait(None)
            pool.close()
            pool.join()

    listener.join()