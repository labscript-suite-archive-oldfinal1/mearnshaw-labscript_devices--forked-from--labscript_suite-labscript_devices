# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'dac_range.ui'
#
# Created: Thu Jul 10 10:41:25 2014
#      by: pyside-uic 0.2.15 running on PySide 1.2.2
#
# WARNING! All changes made in this file will be lost!

from PySide import QtCore, QtGui

class Ui_DACRangeSelector(object):
    def setupUi(self, DACRangeSelector):
        DACRangeSelector.setObjectName("DACRangeSelector")
        DACRangeSelector.resize(379, 295)
        self.verticalLayout = QtGui.QVBoxLayout(DACRangeSelector)
        self.verticalLayout.setObjectName("verticalLayout")
        self.OutputName = QtGui.QLabel(DACRangeSelector)
        self.OutputName.setAlignment(QtCore.Qt.AlignCenter)
        self.OutputName.setObjectName("OutputName")
        self.verticalLayout.addWidget(self.OutputName)
        self.DACRangeComboBox = QtGui.QComboBox(DACRangeSelector)
        self.DACRangeComboBox.setObjectName("DACRangeComboBox")
        self.DACRangeComboBox.addItem("")
        self.DACRangeComboBox.addItem("")
        self.DACRangeComboBox.addItem("")
        self.DACRangeComboBox.addItem("")
        self.DACRangeComboBox.addItem("")
        self.DACRangeComboBox.addItem("")
        self.verticalLayout.addWidget(self.DACRangeComboBox)

        self.retranslateUi(DACRangeSelector)
        QtCore.QMetaObject.connectSlotsByName(DACRangeSelector)

    def retranslateUi(self, DACRangeSelector):
        DACRangeSelector.setWindowTitle(QtGui.QApplication.translate("DACRangeSelector", "Form", None, QtGui.QApplication.UnicodeUTF8))
        self.OutputName.setText(QtGui.QApplication.translate("DACRangeSelector", "TextLabel", None, QtGui.QApplication.UnicodeUTF8))
        self.DACRangeComboBox.setItemText(0, QtGui.QApplication.translate("DACRangeSelector", "0 to 5 V", None, QtGui.QApplication.UnicodeUTF8))
        self.DACRangeComboBox.setItemText(1, QtGui.QApplication.translate("DACRangeSelector", "0 to 10 V", None, QtGui.QApplication.UnicodeUTF8))
        self.DACRangeComboBox.setItemText(2, QtGui.QApplication.translate("DACRangeSelector", "-2.5 to 2.5 V", None, QtGui.QApplication.UnicodeUTF8))
        self.DACRangeComboBox.setItemText(3, QtGui.QApplication.translate("DACRangeSelector", "-2.5 to 7.5 V", None, QtGui.QApplication.UnicodeUTF8))
        self.DACRangeComboBox.setItemText(4, QtGui.QApplication.translate("DACRangeSelector", "-5 to 5 V", None, QtGui.QApplication.UnicodeUTF8))
        self.DACRangeComboBox.setItemText(5, QtGui.QApplication.translate("DACRangeSelector", "-10 to 10 V", None, QtGui.QApplication.UnicodeUTF8))

