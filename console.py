import os
import sys
import traceback
import inspect
import textwrap

from PySide import QtCore
from PySide import QtGui

import code
import StringIO
from contextlib import contextmanager

from threading import Thread, Event

@contextmanager
def redirected(out=sys.stdout, err=sys.stderr):
    saved = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        yield
    finally:
        sys.stdout, sys.stderr = saved


# adapted from https://stackoverflow.com/questions/2758159/how-to-embed-a-python-interpreter-in-a-pyqt-widget
class ConsoleWidget(QtGui.QPlainTextEdit):

    def __init__(self, locals_={}, parent=None):
        QtGui.QPlainTextEdit.__init__(self, parent)

        self.help_str = textwrap.dedent("""
                                        Type 'outputs' for a list of available output names
                                        To set values:  output_name.value = new_value

                                        {}
                                        """).format('\n'.join([': '.join([member, repr(locals_[member].__doc__)])
                                                    for member in locals_
                                                    if inspect.isfunction(locals_[member])]))

        self.prompt = '>>> '
        self.threads = []
        self.history = []
        self.namespace = locals_
        self.construct = []
        self.console = code.InteractiveConsole(locals=self.namespace)

        self.setGeometry(50, 75, 600, 400)
        self.setWordWrapMode(QtGui.QTextOption.WrapAnywhere)
        self.setUndoRedoEnabled(False)
        self.document().setDefaultFont(QtGui.QFont("monospace", 10, QtGui.QFont.Normal))
        self.show_message(self.help_str)

    def kill_threads(self):
        for thread in threads:
            thread.kill()

    def update_namespace(self, namespace):
        self.namespace.update(namespace)

    def show_message(self, message):
        self.appendPlainText(message)
        self.new_prompt()

    def new_prompt(self):
        if self.construct:
            prompt = '.' * len(self.prompt)
        else:
            prompt = self.prompt
        self.appendPlainText(prompt)
        self.moveCursor(QtGui.QTextCursor.End)

    @property
    def command(self):
        doc = self.document()
        curr_line = unicode(doc.findBlockByLineNumber(doc.lineCount() - 1).text())
        curr_line = curr_line.rstrip()
        curr_line = curr_line[len(self.prompt):]
        return curr_line

    @command.setter
    def command(self, command):
        if self.command == command:
            return
        self.moveCursor(QtGui.QTextCursor.End)
        self.moveCursor(QtGui.QTextCursor.StartOfLine, QtGui.QTextCursor.KeepAnchor)
        for i in range(len(self.prompt)):
            self.moveCursor(QtGui.QTextCursor.Right, QtGui.QTextCursor.KeepAnchor)
        self.textCursor().removeSelectedText()
        self.textCursor().insertText(command)
        self.moveCursor(QtGui.QTextCursor.End)

    def get_construct(self, command):
        if self.construct:
            prev_command = self.construct[-1]
            self.construct.append(command)
            if not prev_command and not command:
                ret_val = '\n'.join(self.construct)
                self.construct = []
                return ret_val
            else:
                return ''
        else:
            if command and command[-1] == (':'):
                self.construct.append(command)
                return ''
            else:
                return command

    def add_to_history(self, command):
        if command and (not self.history or self.history[-1] != command):
            self.history.append(command)
        self.history_index = len(self.history)

    @property
    def prev_history_entry(self):
        if self.history:
            self.history_index = max(0, self.history_index - 1)
            return self.history[self.history_index]
        return ''

    @property
    def next_history_entry(self):
        if self.history:
            hist_len = len(self.history)
            self.history_index = min(hist_len, self.history_index + 1)
            if self.history_index < hist_len:
                return self.history[self.history_index]
        return ''

    @property
    def cursor_position(self):
        return self.textCursor().columnNumber() - len(self.prompt)

    @cursor_position.setter
    def cursor_position(self, position):
        self.moveCursor(QtGui.QTextCursor.StartOfLine)
        for i in range(len(self.prompt) + position):
            self.moveCursor(QtGui.QTextCursor.Right)

    def run_command(self):
        command = self.command
        self.add_to_history(command)

        command = self.get_construct(command)

        if command:
            tmp_stdout = sys.stdout

            class stdoutProxy():
                def __init__(self, write_func):
                    self.write_func = write_func
                    self.skip = False

                def write(self, text):
                    if not self.skip:
                        stripped_text = text.rstrip('\n')
                        self.write_func(stripped_text)
                        QtCore.QCoreApplication.processEvents()
                    self.skip = not self.skip

            sys.stdout = stdoutProxy(self.appendPlainText)
            try:
                try:
                    # update namespace
                    self.console.locals = self.namespace
                    out, err = StringIO.StringIO(), StringIO.StringIO()
                    with redirected(out, err):
                        #result = eval(command, self.namespace, self.namespace)
                        t = KThread(target=self.console.push, args=(command,))
                        #t.daemon = True
                        t.start()
                        self.threads.append(t)
                        #self.console.push(command)
                        result = out.getvalue().strip()
                        err = err.getvalue()
                    if not err:
                        if result:
                            self.appendPlainText(repr(result))
                    else:
                        self.appendPlainText(repr(err))
                except SyntaxError:
                    exec command in self.namespace
            except SystemExit:
                self.close()
            """
            except:
                traceback_lines = traceback.format_exc().split('\n')
                # Remove traceback mentioning this file, and a linebreak
                for i in (3,2,1,-1):
                    traceback_lines.pop(i)
                self.appendPlainText('\n'.join(traceback_lines))
            """
            sys.stdout = tmp_stdout
        self.new_prompt()

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Enter, QtCore.Qt.Key_Return):
            self.run_command()
            return
        if event.key() == QtCore.Qt.Key_Home:
            self.cursor_position = 0
            return
        if event.key() == QtCore.Qt.Key_PageUp:
            return
        elif event.key() in (QtCore.Qt.Key_Left, QtCore.Qt.Key_Backspace):
            if self.cursor_position == 0:
                return
        elif event.key() == QtCore.Qt.Key_Up:
            self.command = self.prev_history_entry
            return
        elif event.key() == QtCore.Qt.Key_Down:
            self.command = self.next_history_entry
            return
        elif event.key() == QtCore.Qt.Key_D and event.modifiers() == QtCore.Qt.ControlModifier:
            self.close()
        super(ConsoleWidget, self).keyPressEvent(event)


# from https://mail.python.org/pipermail/python-list/2004-May/281943.html
class KThread(Thread):
    """A subclass of threading.Thread, with a kill() method."""

    def __init__(self, *args, **keywords):
        threading.Thread.__init__(self, *args, **keywords)
        self.killed = False

    def start(self):
        """Start the thread."""
        self.__run_backup = self.run
        self.run = self.__run      # Force the Thread to install our trace.
        threading.Thread.start(self)

    def __run(self):
        """Hacked run function, which installs the trace."""
        sys.settrace(self.globaltrace)
        self.__run_backup()
        self.run = self.__run_backup

    def globaltrace(self, frame, why, arg):
        if why == 'call':
            return self.localtrace
        else:
            return None

    def localtrace(self, frame, why, arg):
        if self.killed:
            if why == 'line':
                raise SystemExit()
        return self.localtrace

    def kill(self):
        self.killed = True
