#!/usr/bin/env python

from bottle import Bottle, template, request
from pstats import Stats
try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO
import argparse
import urllib
import os
import re


VERSION = '0.1.4'

__doc__ = """\
A thin wrapper for viewing python cProfile output.

It provides a simple html view of the pstats.Stats object that is generated
from when a python script is run with the -m cProfile flag.

"""


stats_template = """\
    <html>
        <head>
            <title>{{ filename }} | cProfile Results</title>
        </head>
        <body>
            <pre>{{ !stats }}</pre>

            % if callers:
                <h2>Called By:</h2>
                <pre>{{ !callers }}</pre>

            % if callees:
                <h2>Called:</h2>
                <pre>{{ !callees }}</pre>
        </body>
    </html>"""

index_template = """\
    <html>
        <head>
            <title>cProfile Results Index</title>
        </head>
        <body>
            <h1>cProfile Statistics:</h1>

            % if links:
                <h3>Loaded pStats files:</h3>
                <pre>{{ !links }}</pre>
            % end

            % if unsupported_links:
                </br>
                <h3>Unsupported files:</h3>
                <pre>{{ !unsupported_links }}</pre>
            % end
        </body>
    </html>"""


SORT_KEY = 'sort'
FUNC_NAME_KEY = 'func_name'


def get_href(key, val):
    href = '?'
    query = dict(request.query)
    query[key] = val
    for key in query.keys():
        href += '%s=%s&' % (key, query[key])
    return href[:-1]


class CProfileVStats(object):
    """Wrapper around pstats.Stats class."""
    def __init__(self, output_file):
        self.output_file = output_file
        self.obj = Stats(output_file)
        self.reset_stream()

    def reset_stream(self):
        self.obj.stream = StringIO()

    def read(self):
        value = self.obj.stream.getvalue()
        self.reset_stream()

        # process stats output
        value = self._process_header(value)
        value = self._process_lines(value)
        return value

    IGNORE_FUNC_NAMES = ['function', '']
    STATS_LINE_REGEX = r'(.*)\((.*)\)$'
    HEADER_LINE_REGEX = r'ncalls|tottime|cumtime'
    DEFAULT_SORT_ARG = 'cumulative'
    SORT_ARGS = {
        'ncalls': 'calls',
        'tottime': 'time',
        'cumtime': 'cumulative',
        'filename': 'module',
        'lineno': 'nfl',
    }

    @classmethod
    def _process_header(cls, output):
        lines = output.splitlines(True)
        for idx, line in enumerate(lines):
            match = re.search(cls.HEADER_LINE_REGEX, line)
            if match:
                for key, val in cls.SORT_ARGS.items():
                    url_link = template(
                        "<a href='{{ url }}'>{{ key }}</a>",
                        url=get_href(SORT_KEY, val),
                        key=key)
                    line = line.replace(key, url_link)
                lines[idx] = line
                break
        return ''.join(lines)

    @classmethod
    def _process_lines(cls, output):
        lines = output.splitlines(True)
        for idx, line in enumerate(lines):
            match = re.search(cls.STATS_LINE_REGEX, line)
            if match:
                prefix = match.group(1)
                func_name = match.group(2)

                if func_name not in cls.IGNORE_FUNC_NAMES:
                    url_link = template(
                        "<a href='{{ url }}'>{{ func_name }}</a>",
                        url=get_href(FUNC_NAME_KEY, func_name),
                        func_name=func_name)

                    lines[idx] = template(
                        "{{ prefix }}({{ !url_link }})\n",
                        prefix=prefix, url_link=url_link)

        return ''.join(lines)

    def show(self, restriction=''):
        self.obj.print_stats(restriction)
        return self

    def show_callers(self, func_name):
        self.obj.print_callers(func_name)
        return self

    def show_callees(self, func_name):
        self.obj.print_callees(func_name)
        return self

    def sort(self, sort=''):
        sort = sort or self.DEFAULT_SORT_ARG
        self.obj.sort_stats(sort)
        return self


class CProfileV(object):
    def __init__(self, cprofile_output, watch_directory=None,
                 address='127.0.0.1', port=4000, quiet=True):
        self.cprofile_output = cprofile_output
        self.port = port
        self.address = address
        self.quiet = quiet
        self.app = Bottle()

        if os.path.isdir(watch_directory):
            self.watch_directory = os.path.normpath(watch_directory)
        else:
            self.watch_directory = None

        self.setup_routing()

    def load_stats_objects(self):
        self.stats_obj = {}
        self.unsupported_files = []

        if self.watch_directory:
            directory_entries = os.listdir(self.watch_directory)
            cprofile_output_files = [
                d for d in directory_entries if os.path.isfile(d)
            ]
        else:
            cprofile_output_files = self.cprofile_output

        for cprofile_output in cprofile_output_files:
            try:
                stats_object = CProfileVStats(cprofile_output)
            except Exception:
                self.unsupported_files.append(cprofile_output)
            else:
                self.stats_obj[cprofile_output] = stats_object

    def setup_routing(self):
        self.app.route('/', 'GET', self.index)
        self.app.route('/cprofile_output/<name>', 'GET', self.route_handler)

    def index(self):
        if self.watch_directory:
            self.load_stats_objects()

        links_html = ''
        link_template = '<a href="/cprofile_output/{2}">{2}</a><br />'
        for cprofile_output in self.stats_obj.keys():
            links_html += link_template.format(
                self.address, self.port, urllib.quote_plus(cprofile_output)
            )

        unsupported_links_html = ''
        for cprofile_output in self.unsupported_files:
            unsupported_links_html += cprofile_output + '<br />'

        data = {
            'links': links_html,
            'unsupported_links': unsupported_links_html,
        }
        return template(index_template, **data)

    def route_handler(self, name):
        func_name = request.query.get(FUNC_NAME_KEY) or ''
        sort = request.query.get(SORT_KEY) or ''

        stats_obj = self.stats_obj[name]

        stats = stats_obj.sort(sort).show(func_name).read()
        if func_name:
            callers = stats_obj.sort(sort).show_callers(func_name).read()
            callees = stats_obj.sort(sort).show_callees(func_name).read()
        else:
            callers = ''
            callees = ''

        data = {
            'filename': self.cprofile_output,
            'stats': stats,
            'callers': callers,
            'callees': callees,
        }
        return template(stats_template, **data)

    def start(self):
        """Starts bottle server."""
        print('cprofilev server listening on port %s\n' % self.port)
        self.app.run(host=self.address, port=self.port, quiet=self.quiet)


def main():
    parser = argparse.ArgumentParser(
        description='Thin wrapper for viewing python cProfile output.')

    parser.add_argument('--version', action='version', version=VERSION)

    parser.add_argument('-v', '--verbose', action='store_const', const=True)
    parser.add_argument('-a', '--address', type=str, default='127.0.0.1',
                        help='specify the address to listen on. '
                        '(defaults to 127.0.0.1)')
    parser.add_argument('-p', '--port', type=int, default=4000,
                        help='specify the port to listen on. '
                        '(defaults to 4000)')
    parser.add_argument('-w', '--watch', type=str,
                        help='specify a directory to watch for cProfile '
                        'output files. If added ignores other arguments.')
    parser.add_argument('cprofile_output', help='The cProfile output to view.',
                        default=[], nargs='*')
    args = vars(parser.parse_args())

    port = args['port']
    address = args['address']
    cprofile_output = args['cprofile_output']
    watch_directory = args['watch']
    quiet = not args['verbose']

    CProfileV(cprofile_output, watch_directory, address, port, quiet).start()


if __name__ == '__main__':
    main()
