# for localized messages
from . import _

import re
from os.path import exists
from os import makedirs

from enigma import eTimer, eDVBDB, eServiceReference

from Components.ActionMap import ActionMap
from Components.config import config, ConfigSelection, ConfigSubsection, getConfigListEntry
from Components.Label import Label
from Components.NimManager import nimmanager
from Components.Sources.StaticText import StaticText

from Plugins.Plugin import PluginDescriptor

from Screens.Screen import Screen, ScreenSummary
from Screens.Setup import Setup

config.plugins.BouquetCleanup = ConfigSubsection()
config.plugins.BouquetCleanup.source = ConfigSelection(choices=["/etc/enigma2", "/tmp/bouquets"], default="/etc/enigma2")
config.plugins.BouquetCleanup.target = ConfigSelection(choices=["/etc/enigma2", "/tmp/bouquets/new"], default="/etc/enigma2")


class BouquetCleanupSetup(Setup):
	def __init__(self, session):
		Setup.__init__(self, session=session, setup="bouquetcleanup")

	def createSetup(self):
		self.list = []
		self.list.append(getConfigListEntry("From", config.plugins.BouquetCleanup.source, "Source location of the bouquets you want to clean up. '/etc/enigma2' is the default location. The location '/tmp/bouquets' is just provided for testing purposes."))
		self.list.append(getConfigListEntry("To", config.plugins.BouquetCleanup.target, "Target location where you want the cleaned bouquets to be saved. '/etc/enigma2' is the default location. The location in '/tmp/bouquets/new' is just provided for testing purposes. If the source and target locations are the same the new 'cleaned' bouquets will overwrite the originals."))
		currentItem = self["config"].getCurrent()
		self["config"].list = self.list
		self.moveToItem(currentItem)

	def createSetupList(self): # PLi
		self.createSetup()


class BouquetsReader():
	def __init__(self, path=None):
		default_path = "/etc/enigma2"
		self.path = default_path if path is None else path
		self.bouquetsDict = {"tv": [], "radio": []} # prefilled just in case no bouquet index exists
		self.readBouquetsIndex()
		self.readBouquets()

	def parseBouquetIndex(self, path, content):
		ret = []
		rows = content.split("\n")
		for row in rows:
			row = row.strip()
			result = re.match("^.*FROM BOUQUET \"(.+)\" ORDER BY.*$", row) or re.match("[#]SERVICE[:] (?:[0-9a-f]+[:])+([^:]+[.](?:tv|radio))$", row, re.IGNORECASE)
			if result is None:
				ret.append({"row": row})
				continue
			filename = result.group(1)
			try:
				firstline = open(path + "/" + filename, "rb").read().split(b"\n")[0].decode(errors="ignore")
			except Exception as e:
				continue
			if firstline[:6] == "#NAME ":
				bouquetname = firstline[6:]
			else:
				bouquetname = "Unknown"
			ret.append({"row": row, "filename": filename, "name": bouquetname})
		return ret

	def readBouquetsIndex(self):
		ret = {}
		for bouquet_type in ["tv", "radio"]:
			try:
				content = open(self.path + "/bouquets." + bouquet_type, "r").read()
			except Exception as e:
				continue
			ret[bouquet_type] = self.parseBouquetIndex(self.path, content)
		self.bouquetsDict = ret

	def readBouquets(self):
		for bouquet_type in ["tv", "radio"]:
			for i, row in enumerate(self.bouquetsDict[bouquet_type][:]):
				if "filename" in row:
					try:
						content = open(self.path + "/" + row["filename"], "rb").read().decode(errors="ignore").split("\n")
					except Exception as e:
						continue
					newContent = []
					for item in content:
						item = item.strip("\n")
						if newContent and item[:13] == "#DESCRIPTION ":
							newContent[-1] += "\n" + item
						else:
							newContent.append(item)
					self.bouquetsDict[bouquet_type][i]["content"] = newContent
					
	def getBouquetsDict(self):
		return self.bouquetsDict


class BouquetsWriter():
	def __init__(self, path=None):
		default_path = "/etc/enigma2" # "/tmp/bouquets" #
		self.path = default_path if path is None else path

	def writeBouquets(self, bouquetsDict, showAll=False):
		for bouquet_type in ["tv", "radio"]:
			exists(self.path) or makedirs(self.path) # just here for testing to alternative paths
			bouquetIndex = []
			for row in bouquetsDict[bouquet_type]:
				if "content" in row:
					current_bouquet_list = []
					for item in row["content"]:
						current_bouquet_list.append(item)
					bouquet_current = open(self.path + "/%s" % row["filename"], "w")
					bouquet_current.write('\n'.join(current_bouquet_list))
					bouquet_current.close()
					del current_bouquet_list
					row_split = row["row"].split(":")
					# Hide empty bouquets, but, special case, don't ever hide userbouquet.LastScanned.tv or userbouquet.favourites.tv or userbouquet.favourites.radio even if they are empty.
					if not showAll and not row["hasActiveServices"] and not row["filename"] in ("userbouquet.LastScanned.tv", "userbouquet.favourites.tv", "userbouquet.favourites.radio"):
						row_split[1] = str(int(row_split[1]) | eServiceReference.isInvisible) # flip to invisible if was visible
					else:
						row_split[1] = str(int(row_split[1]) & ~eServiceReference.isInvisible) # flip to visible if was invisible
					row["row"] = ":".join(row_split)
				bouquetIndex.append(row["row"])
			if bouquetIndex:
				index_current = open(self.path + "/bouquets.%s" % bouquet_type, "w")
				index_current.write('\n'.join(bouquetIndex))
				index_current.close()
				del bouquetIndex


class BouquetCleanup(Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		self.title = _("BouquetCleanup")
		self.skinName = ["BouquetCleanup", "Setup"]
		self.greenText = _("Clean bouquets")
		self.yellowText = _("Reinstate hidden")
		self["key_green"] = StaticText(self.greenText)
		self["key_yellow"] = StaticText(self.yellowText)
		self["key_red"] = StaticText(_("Exit"))
		self["key_menu"] = StaticText(_("MENU"))
		self["saveactions"] = ActionMap(["ColorActions"],
		{
			"green": self.keySave,
		}, -3)
		self["reinstateactions"] = ActionMap(["ColorActions"],
		{
			"yellow": self.showAll,
		}, -3)
		self["cancelactions"] = ActionMap(["CancelSaveActions", "MenuActions"],
		{
			"cancel": self.keyCancel,
			"menu": self.keyMenu,
		}, -3)
		self["config"] = Label(_("Press 'GREEN' to run a clean-up on your bouquets.\nChannels on satellites that are not configured will be hidden.\nEmpty bouquets will also be hidden.\nRun again after any tuner reconfiguration.\n\nPress 'YELLOW' to reinstate all hidden services.\n\nPress 'MENU' to access this plugin's configuration setup."))

		self.bouquetsDict = {}
		self.active_orbitals = []
		self.summaryCallbacks = []
		self.hideNotConfiguredServices = True # opposite is reinstate all services

		for nim in nimmanager.nim_slots:
			if nim.isCompatible("DVB-S"):
				if getattr(nim, "config_mode_dvbs", nim.config_mode) not in ("loopthrough", "satposdepends", "nothing"):
					self.active_orbitals.extend([sat[0] for sat in nimmanager.getSatListForNim(nim.slot)])
			elif nim.isCompatible("DVB-T"):
				if getattr(nim, "config_mode_dvbt", nim.config_mode) != "nothing":
					self.active_orbitals.append(0xeeee)
			elif nim.isCompatible("DVB-C"):
				if getattr(nim, "config_mode_dvbc", nim.config_mode) != "nothing":
					self.active_orbitals.append(0xffff)
		self.active_orbitals = sorted(list(dict.fromkeys(self.active_orbitals)))

	def keySave(self):
		self.timer = eTimer()
		self.timer.callback.append(self.processBouquets)
		self.timer.start(100, 1)
		self["config"].setText(_("The process is currently running. Please wait!"))
		self["saveactions"].setEnabled(False)
		self["reinstateactions"].setEnabled(False)
		self["key_green"].text = ""
		self["key_yellow"].text = ""
		self.updateSummary()

	def showAll(self):
		self.hideNotConfiguredServices = False
		self.keySave()

	def keyMenu(self):
		self.session.open(BouquetCleanupSetup)

	def processBouquets(self):
		self.bouquetsDict = BouquetsReader(config.plugins.BouquetCleanup.source.value).getBouquetsDict()
		for bouquet_type in ["tv", "radio"]:
			for i, row in enumerate(self.bouquetsDict[bouquet_type][:]):
				if "content" in row:
					numActiveServices = 0
					for j, item in enumerate(row["content"][:]):
						if item.startswith("#SERVICE ") and not ":http" in item:
							item_split = item.split(":")
							if len(item_split) > 7 and (int(item_split[1]) & ~eServiceReference.isInvisible) == 0: # playable
								if self.hideNotConfiguredServices and (int(item_split[6], 16) >> 16) not in self.active_orbitals:
									self.bouquetsDict[bouquet_type][i]["content"][j] = self.invisible(item_split)  # flip to invisible if was visible
								else:
									self.bouquetsDict[bouquet_type][i]["content"][j] = self.reinstate(item_split) # flip to visible if was invisible
									numActiveServices += 1
						elif item.startswith("#SERVICE ") and ":http" in item:
							numActiveServices += 1 # count IPTV as active service
					self.bouquetsDict[bouquet_type][i]["hasActiveServices"] = numActiveServices
		BouquetsWriter(config.plugins.BouquetCleanup.target.value).writeBouquets(self.bouquetsDict, showAll=not self.hideNotConfiguredServices)
		# reload
		if config.plugins.BouquetCleanup.target.value == config.plugins.BouquetCleanup.target.default:
			eDVBDB.getInstance().reloadServicelist()
			eDVBDB.getInstance().reloadBouquets()
		self["config"].setText(_("Process complete."))
		self.updateSummary()
		if self.hideNotConfiguredServices:
			self["reinstateactions"].setEnabled(True)
			self["key_yellow"].text = self.yellowText
		else:
			self["saveactions"].setEnabled(True)
			self["key_green"].text = self.greenText
		self.hideNotConfiguredServices = True # return to default state

	def invisible(self, item_split):
		item_split[1] = str(int(item_split[1]) | eServiceReference.isInvisible)
		return ":".join(item_split)

	def reinstate(self, item_split):
		item_split[1] = str(int(item_split[1]) & ~eServiceReference.isInvisible)
		return ":".join(item_split)

	def keyCancel(self):
		self.close()

	def createSummary(self):
		return BouquetCleanupSummary

	def updateSummary(self):
		for x in self.summaryCallbacks:
			if callable(x):
				x()


class BouquetCleanupSummary(ScreenSummary):
	def __init__(self, session, parent):
		ScreenSummary.__init__(self, session, parent=parent)
		self.skinName =["BouquetCleanupSummary", "MenuHorizontalSummary"]
		self["title"] = StaticText(self.parent.title)
		self["entry"] = StaticText()
		if self.addWatcher not in self.onShow:
			self.onShow.append(self.addWatcher)
		if self.removeWatcher not in self.onHide:
			self.onHide.append(self.removeWatcher)

	def addWatcher(self):
		if self.selectionChanged not in self.parent.summaryCallbacks:
			self.parent.summaryCallbacks.append(self.selectionChanged)
		self.selectionChanged()

	def removeWatcher(self):
		if self.selectionChanged in self.parent.summaryCallbacks:
			self.parent.summaryCallbacks.remove(self.selectionChanged)

	def selectionChanged(self):
		self["entry"].text = self.parent["config"].text
		

def main(session, **kwargs):
	session.open(BouquetCleanup)

def Plugins(**kwargs):
	list = []

	list.append(
		PluginDescriptor(name=_("Bouquets clean-up"),
		description=_("Clears out channels on not configured satellites"),
		where = [PluginDescriptor.WHERE_PLUGINMENU],
		needsRestart = False,
		fnc = main))

	return list