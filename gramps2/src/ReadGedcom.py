#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2000-2004  Donald N. Allingham
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#

# $Id$

"Import from GEDCOM"

#-------------------------------------------------------------------------
#
# standard python modules
#
#-------------------------------------------------------------------------
import os
import re
import string
import const
import time

#-------------------------------------------------------------------------
#
# GTK/GNOME Modules
#
#-------------------------------------------------------------------------
import gtk
import gtk.glade

#-------------------------------------------------------------------------
#
# GRAMPS modules
#
#-------------------------------------------------------------------------
import Errors
import RelLib
import Date
import DateParser
from ansel_utf8 import ansel_to_utf8
import latin_utf8 
import Utils
from GedcomInfo import *
from QuestionDialog import ErrorDialog
from gettext import gettext as _

#-------------------------------------------------------------------------
#
# constants
#
#-------------------------------------------------------------------------
ANSEL = 1
UNICODE = 2
UPDATE = 25

callback = None

_title_string = _("GEDCOM")

def nocnv(s):
    return unicode(s)

file_systems = {
    'VFAT'    : _('Windows 9x file system'),
    'FAT'     : _('Windows 9x file system'),
    "NTFS"    : _('Windows NT file system'),
    "ISO9660" : _('CD ROM'),
    "SMBFS"   : _('Networked Windows file system')
    }

#-------------------------------------------------------------------------
#
# GEDCOM events to GRAMPS events conversion
#
#-------------------------------------------------------------------------
ged2gramps = {}
for _val in const.personalConstantEvents.keys():
    _key = const.personalConstantEvents[_val]
    if _key != "":
        ged2gramps[_key] = _val

ged2fam = {}
for _val in const.familyConstantEvents.keys():
    _key = const.familyConstantEvents[_val]
    if _key != "":
        ged2fam[_key] = _val

#-------------------------------------------------------------------------
#
# regular expressions
#
#-------------------------------------------------------------------------
intRE = re.compile(r"\s*(\d+)\s*$")
lineRE = re.compile(r"\s*(\d+)\s+(\S+)\s*(.*)$")
headRE = re.compile(r"\s*(\d+)\s+HEAD")
nameRegexp= re.compile(r"/?([^/]*)(/([^/]*)(/([^/]*))?)?")
snameRegexp= re.compile(r"/([^/]*)/([^/]*)")
calRegexp = re.compile(r"\s*(ABT|BEF|AFT)?\s*@#D([^@]+)@\s*(.*)$")
rangeRegexp = re.compile(r"\s*BET\s+@#D([^@]+)@\s*(.*)\s+AND\s+@#D([^@]+)@\s*(.*)$")
spanRegexp = re.compile(r"\s*FROM\s+@#D([^@]+)@\s*(.*)\s+TO\s+@#D([^@]+)@\s*(.*)$")

#-------------------------------------------------------------------------
#
#
#
#-------------------------------------------------------------------------
def importData(database, filename, cb=None, use_trans=True):

    global callback
    
    f = open(filename,"r")

    ansel = False
    gramps = False
    for index in range(0,50):
        line = f.readline().split()
        if len(line) == 0:
            break
        if line[1] == 'CHAR' and line[2] == "ANSEL":
            ansel = True
        if line[1] == 'SOUR' and line[2] == "GRAMPS":
            gramps = True
    f.close()

    if not gramps and ansel:
        glade_file = "%s/gedcomimport.glade" % os.path.dirname(__file__)
        top = gtk.glade.XML(glade_file,'encoding','gramps')
        code = top.get_widget('codeset')
        code.set_active(0)
        dialog = top.get_widget('encoding')
        dialog.run()
        codeset = code.get_active()
        dialog.destroy()
    else:
        codeset = None
    import2(database, filename, cb, codeset, use_trans)
        

def import2(database, filename, cb, codeset, use_trans):
    # add some checking here

    glade_file = "%s/gedcomimport.glade" % os.path.dirname(__file__)
    if not os.path.isfile(glade_file):
        glade_file = "plugins/gedcomimport.glade"

    statusTop = gtk.glade.XML(glade_file,"status","gramps")
    statusWindow = statusTop.get_widget("status")

    Utils.set_titles(statusWindow,statusTop.get_widget('title'),
                     _('GEDCOM import status'))
    
    statusTop.get_widget("close").set_sensitive(0)
    statusTop.signal_autoconnect({
        "destroy_passed_object" : Utils.destroy_passed_object
        })

    try:
        g = GedcomParser(database,filename,statusTop, codeset)
    except IOError,msg:
        Utils.destroy_passed_object(statusWindow)
        ErrorDialog(_("%s could not be opened\n") % filename,str(msg))
        return
    except:
        Utils.destroy_passed_object(statusWindow)
        DisplayTrace.DisplayTrace()
        return

    if database.get_number_of_people() == 0:
        use_trans = False

    try:
        close = g.parse_gedcom_file(use_trans)
    except IOError,msg:
        Utils.destroy_passed_object(statusWindow)
        errmsg = _("%s could not be opened\n") % filename
        ErrorDialog(errmsg,str(msg))
        return
    except Errors.GedcomError, val:
        (m1,m2) = val.messages()
        Utils.destroy_passed_object(statusWindow)
        ErrorDialog(m1,m2)
        return
    except:
        import DisplayTrace
        Utils.destroy_passed_object(statusWindow)
        DisplayTrace.DisplayTrace()
        return
    
    statusTop.get_widget("close").set_sensitive(1)
    if close:
        statusWindow.destroy()

    if cb:
        statusWindow.destroy()
        cb(1)
    elif callback:
        callback()

#-------------------------------------------------------------------------
#
#
#
#-------------------------------------------------------------------------
class DateStruct:
    def __init__(self):
        self.date = ""
        self.time = ""

class GedcomDateParser(DateParser.DateParser):

    month_to_int = {
        'jan' : 1,  'feb' : 2,  'mar' : 3,  'apr' : 4,
        'may' : 5,  'jun' : 6,  'jul' : 7,  'aug' : 8,
        'sep' : 9,  'oct' : 10, 'nov' : 11, 'dec' : 12,
        }

#-------------------------------------------------------------------------
#
#
#
#-------------------------------------------------------------------------
class GedcomParser:

    SyntaxError = "Syntax Error"
    BadFile = "Not a GEDCOM file"

    def __init__(self, dbase, filename, window, codeset):
        self.dp = GedcomDateParser()
        self.db = dbase
        self.person = None
        self.media_map = {}
        self.fmap = {}
        self.smap = {}
        self.nmap = {}
        self.share_note = []
        self.refn = {}
        self.added = {}
        self.gedmap = GedcomInfoDB()
        self.gedsource = None
        self.def_src = RelLib.Source()
        fname = os.path.basename(filename).split('\\')[-1]
        self.def_src.set_title(_("Import from %s") % unicode(fname))
        self.dir_path = os.path.dirname(filename)
        self.localref = 0
        self.placemap = {}
        self.broken_conc_list = [ 'FamilyOrigins', 'FTW' ]
        self.broken_conc = 0
        self.is_ftw = 0
        self.idswap = {}
        self.gid2id = {}
        self.sid2id = {}
        self.lid2id = {}
        self.fid2id = {}

        self.f = open(filename,"rU")
        self.filename = filename
        self.index = 0
        self.backoff = 0
        self.override = codeset

        if self.db.get_number_of_people() == 0:
            self.map_gid = self.map_gid_empty
        else:
            self.map_gid = self.map_gid_not_empty

        if self.override != 0:
            if self.override == 1:
                self.cnv = ansel_to_utf8
            elif self.override == 2:
                self.cnv = latin_utf8.latin_to_utf8
            else:
                self.cnv = nocnv
        else:
            self.cnv = nocnv

        self.geddir = os.path.dirname(os.path.normpath(os.path.abspath(filename)))
    
        self.transtable = string.maketrans('','')
        self.delc = self.transtable[0:31]
        self.transtable2 = self.transtable[0:128] + ('?' * 128)
        
        self.window = window
        if window:
            self.file_obj = window.get_widget("file")
            self.encoding_obj = window.get_widget("encoding")
            self.created_obj = window.get_widget("created")
            self.version_obj = window.get_widget("version")
            self.families_obj = window.get_widget("families")
            self.people_obj = window.get_widget("people")
            self.errors_obj = window.get_widget("errors")
            self.close_done = window.get_widget('close_done')
            self.error_text_obj = window.get_widget("error_text")
            self.info_text_obj = window.get_widget("info_text")
            
        self.error_count = 0

        amap = const.personalConstantAttributes
        self.attrs = amap.values()
        self.gedattr = {}
        for val in amap.keys():
            self.gedattr[amap[val]] = val

        if self.window:
            self.update(self.file_obj,os.path.basename(filename))
            
        self.search_paths = []

        try:
            mypaths = []
            f = open("/proc/mounts","r")

            for line in f.xreadlines():
                paths = line.split()
                ftype = paths[2].upper()
                if ftype in file_systems.keys():
                    mypaths.append((paths[1],file_systems[ftype]))
                    self.search_paths.append(paths[1])
            f.close()

            if len(mypaths):
                self.infomsg(_("Windows style path names for images will use the following mount "
                               "points to try to find the images. These paths are based on Windows "
                               "compatible file systems available on this system:\n\n"))
                for p in mypaths:
                    self.infomsg("\t%s : %s\n" % p)
                    
                self.infomsg('\n')
            self.infomsg(_("Images that cannot be found in the specfied path in the GEDCOM file "
                           "will be searched for in the same directory in which the GEDCOM file "
                           "exists (%s).\n") % self.geddir)
        except:
            pass

    def errmsg(self,msg):
        if self.window:
            try:
                self.error_text_obj.get_buffer().insert_at_cursor(msg)
            except TypeError:
                self.error_text_obj.get_buffer().insert_at_cursor(msg,len(msg))
        else:
            print msg

    def infomsg(self,msg):
        if self.window:
            try:
                self.info_text_obj.get_buffer().insert_at_cursor(msg)
            except TypeError:
                self.info_text_obj.get_buffer().insert_at_cursor(msg,len(msg))
        else:
            print msg

    def find_file(self,fullname,altpath):
        tries = []
        fullname = fullname.replace('\\','/')
        tries.append(fullname)
        
        if os.path.isfile(fullname):
            return (1,fullname)
        other = os.path.join(altpath,fullname)
        tries.append(other)
        if os.path.isfile(other):
            return (1,other)
        other = os.path.join(altpath,os.path.basename(fullname))
        tries.append(other)
        if os.path.isfile(other):
            return (1,other)
        if len(fullname) > 3:
            if fullname[1] == ':':
                fullname = fullname[2:]
                for path in self.search_paths:
                    other = os.path.normpath("%s/%s" % (path,fullname))
                    tries.append(other)
                    if os.path.isfile(other):
                        return (1,other)
            return (0,tries)
        else:
            return (0,tries)

    def update(self,field,text):
        field.set_text(text)
        while gtk.events_pending():
            gtk.main_iteration()

    def get_next(self):
        if self.backoff == 0:
            next_line = self.f.readline()
            try:
                self.text = string.translate(next_line.strip(),self.transtable,self.delc)
            except:
                self.text = next_line.strip()

            try:
                self.text = self.cnv(self.text)
            except:
                self.text = string.translate(self.text,self.transtable2)
            
            self.index += 1
            l = self.text.split(None, 2)
            ln = len(l)
            try:
                if ln == 2:
                    self.groups = (int(l[0]),l[1],"")
                else:
                    self.groups = (int(l[0]),l[1],l[2])
            except:
                if self.text == "":
                    msg = _("Warning: line %d was blank, so it was ignored.\n") % self.index
                else:
                    msg = _("Warning: line %d was not understood, so it was ignored.") % self.index
                    msg = "%s\n\t%s\n" % (msg,self.text)
                self.errmsg(msg)
                self.error_count = self.error_count + 1
                self.groups = (999, "XXX", "XXX")
        self.backoff = 0
        return self.groups
            
    def barf(self,level):
        msg = _("Warning: line %d was not understood, so it was ignored.") % self.index
        self.errmsg(msg)
        msg = "\n\t%s\n" % self.text

        self.errmsg(msg)
        self.error_count = self.error_count + 1
        self.ignore_sub_junk(level)

    def warn(self,msg):
        self.errmsg(msg)
        self.error_count = self.error_count + 1

    def backup(self):
        self.backoff = 1

    def parse_gedcom_file(self,use_trans=True):

        if use_trans:
            self.trans = self.db.transaction_begin()
        else:
            self.trans = None
        t = time.time()
        self.index = 0
        self.fam_count = 0
        self.indi_count = 0
        self.source_count = 0
        try:
            self.parse_header()
            self.parse_submitter()
            self.db.add_source(self.def_src,self.trans)
            self.parse_record()
            self.parse_trailer()
        except Errors.GedcomError, err:
            self.errmsg(str(err))
            
        if self.window:
            self.update(self.families_obj,str(self.fam_count))
            self.update(self.people_obj,str(self.indi_count))
            
        self.break_note_links()
        t = time.time() - t
        msg = _('Import Complete: %d seconds') % t

        if use_trans:
            self.db.transaction_commit(self.trans,_("GEDCOM import"))
        
        if self.window:
            self.infomsg("\n%s" % msg)
        else:
            print msg
            print "Families: %d" % self.fam_count
            print "Individuals: %d" % self.indi_count
            return None

    def break_note_links(self):
        for o in self.share_note:
            o.unique_note()
            
    def parse_trailer(self):
        matches = self.get_next()
        if matches[1] != "TRLR":
            self.barf(0)
            self.f.close()
        
    def parse_header(self):
        self.parse_header_head()
        self.parse_header_source()

    def parse_submitter(self):
        matches = self.get_next()
        if matches[2] != "SUBM":
            self.backup()
            return
        else:
            self.parse_submitter_data(1)

    def parse_submitter_data(self,level):
        while(1):
            matches = self.get_next()
            if int(matches[0]) < level:
                self.backup()
                return
            elif matches[1] == "NAME":
                self.def_src.set_author(unicode(matches[2]))
            elif matches[1] == ["ADDR"]:
                self.ignore_sub_junk(level+1)

    def parse_source(self,name,level):
        self.source = self.find_or_create_source(name[1:-1])

        note = ""
        while 1:
            matches = self.get_next()
            if int(matches[0]) < level:
                if note:
                    self.source.set_note(note)
                if not self.source.get_title():
                    self.source.set_title("No title - ID %s" % self.source.get_gramps_id())
                self.db.commit_source(self.source, self.trans)
                self.backup()
                return
            elif matches[1] == "TITL":
                title = matches[2] + self.parse_continue_data(level+1)
                title = title.replace('\n',' ')
                self.source.set_title(title)
            elif matches[1] == "TAXT" or matches[1] == "PERI": # EasyTree Sierra On-Line
                if self.source.get_title() == "":
                    title = matches[2] + self.parse_continue_data(level+1)
                    title = title.replace('\n',' ')
                    self.source.set_title(title)
            elif matches[1] == "AUTH":
                self.source.set_author(matches[2] + self.parse_continue_data(level+1))
            elif matches[1] == "PUBL":
                self.source.set_publication_info(matches[2] + self.parse_continue_data(level+1))
            elif matches[1] == "OBJE":
                self.ignore_sub_junk(2)
            elif matches[1] == "NOTE":
                note = self.parse_note(matches,self.source,level+1,note)
            elif matches[1] == "TEXT":
                note = self.source.get_note()
                d = self.parse_continue_data(level+1)
                if note:
                    note = "%s\n%s %s%s" % (note,matches[1],matches[2],d)
                else:
                    note = "%s %s%s" % (matches[1],matches[2],d)
            elif matches[1] == "ABBR":
                self.source.set_abbreviation(matches[2] + self.parse_continue_data(level+1))
            else:
                note = self.source.get_note()
                if note:
                    note = "%s\n%s %s" % (note,matches[1],matches[2])
                else:
                    note = "%s %s" % (matches[1],matches[2])

    def parse_record(self):
        while 1:
            matches = self.get_next()
            if matches[2] == "FAM":
                if self.fam_count % UPDATE == 0 and self.window:
                    self.update(self.families_obj,str(self.fam_count))
                self.fam_count = self.fam_count + 1
                self.family = self.find_or_create_family(matches[1][1:-1])
                self.parse_family()
                if self.addr != None:
                    father_handle = self.family.get_father_handle()
                    father = self.db.get_person_from_handle(father_handle)
                    if father:
                        father.add_address(self.addr)
                        self.db.commit_person(father, self.trans)
                    mother_handle = self.family.get_mother_handle()
                    mother = self.db.get_person_from_handle(mother_handle)
                    if mother:
                        mother.add_address(self.addr)
                        self.db.commit_person(mother, self.trans)
                    for child_handle in self.family.get_child_handle_list():
                        child = self.db.get_person_from_handle(child_handle)
                        if child:
                            child.add_address(self.addr)
                            self.db.commit_person(child, self.trans)
                if len(self.family.get_source_references()) == 0:
                    sref = RelLib.SourceRef()
                    sref.set_base_handle(self.def_src.get_handle())
                    self.family.add_source_reference(sref)
                self.db.commit_family(self.family, self.trans)
                del self.family
            elif matches[2] == "INDI":
                if self.indi_count % UPDATE == 0 and self.window:
                    self.update(self.people_obj,str(self.indi_count))
                self.indi_count = self.indi_count + 1
                gid = matches[1]
                gid = gid[1:-1]
                self.person = self.find_or_create_person(self.map_gid(gid))
                self.added[self.person.get_handle()] = 1
                self.parse_individual()
                if len(self.person.get_source_references()) == 0:
                    sref = RelLib.SourceRef()
                    sref.set_base_handle(self.def_src.get_handle())
                    self.person.add_source_reference(sref)
                self.db.commit_person(self.person, self.trans)
                del self.person
            elif matches[2] in ["SUBM","SUBN","REPO"]:
                self.ignore_sub_junk(1)
            elif matches[1] in ["SUBM","SUBN","OBJE","_EVENT_DEFN"]:
                self.ignore_sub_junk(1)
            elif matches[2] == "SOUR":
                self.parse_source(matches[1],1)
            elif matches[2][0:4] == "NOTE":
                if self.nmap.has_key(matches[1]):
                    noteobj = self.nmap[matches[1]]
                else:
                    noteobj = RelLib.Note()
                    self.nmap[matches[1]] = noteobj
                text =  matches[2][4:]
#                noteobj.append(text + self.parse_continue_data(1))
                noteobj.append(text + self.parse_note_continue(1))
                self.parse_note_data(1)
            elif matches[1] == "TRLR":
                self.backup()
                return
            else:
                self.barf(1)

    def map_gid_empty(self,gid):
        return gid

    def map_gid_not_empty(self,gid):
        if self.idswap.get(gid):
            return self.idswap[gid]
        else:
            if self.db.id_trans.get(str(gid)):
                self.idswap[gid] = self.db.find_next_gid()
            else:
                self.idswap[gid] = gid
            return self.idswap[gid]

    def find_or_create_person(self,gramps_id):
        person = RelLib.Person()
        intid = self.gid2id.get(gramps_id)
        if self.db.person_map.has_key(intid):
            person.unserialize(self.db.person_map.get(intid))
        else:
            intid = self.find_person_handle(gramps_id)
            person.set_handle(intid)
            person.set_gramps_id(gramps_id)
        return person

    def find_person_handle(self,gramps_id):
        intid = self.gid2id.get(gramps_id)
        if not intid:
            intid = create_id()
            self.gid2id[gramps_id] = intid
        return intid

    def find_or_create_family(self,gramps_id):
        family = RelLib.Family()
        intid = self.fid2id.get(gramps_id)
        if self.db.family_map.has_key(intid):
            family.unserialize(self.db.family_map.get(intid))
        else:
            intid = self.find_family_handle(gramps_id)
            family.set_handle(intid)
            family.set_gramps_id(gramps_id)
        return family

    def find_family_handle(self,gramps_id):
        intid = self.fid2id.get(gramps_id)
        if not intid:
            intid = create_id()
            self.fid2id[gramps_id] = intid
        return intid

    def find_or_create_source(self,gramps_id):
        source = RelLib.Source()
        intid = self.sid2id.get(gramps_id)
        if self.db.source_map.has_key(intid):
            source.unserialize(self.db.source_map.get(intid))
        else:
            intid = create_id()
            source.set_handle(intid)
            source.set_gramps_id(gramps_id)
            self.db.add_source(source,self.trans)
            self.sid2id[gramps_id] = intid
        return source

    def find_or_create_place(self,gramps_id):
        place = RelLib.Place()
        intid = self.lid2id.get(gramps_id)
        if self.db.place_map.has_key(intid):
            place.unserialize(self.db.place_map.get(intid))
        else:
            intid = create_id()
            place.set_handle(intid)
            place.set_title(gramps_id)
            place.set_gramps_id(self.db.find_next_place_gramps_id())
            self.db.add_place(place,self.trans)
            self.lid2id[gramps_id] = intid
        return place

    def parse_cause(self,event,level):
        while 1:
            matches = self.get_next()
            if int(matches[0]) < level:
                self.backup()
                return
            elif matches[1] == "SOUR":
                event.add_source_reference(self.handle_source(matches,level+1))
            else:
                self.barf(1)
                
    def parse_note_data(self,level):
        while 1:
            matches = self.get_next()
            if int(matches[0]) < level:
                self.backup()
                return
            elif matches[1] in ["SOUR","CHAN","REFN"]:
                self.ignore_sub_junk(level+1)
            elif matches[1] == "RIN":
                pass
            else:
                self.barf(level+1)

    def parse_ftw_relations(self,level):
        mrel = "Birth"
        frel = "Birth"
        
        while 1:
            matches = self.get_next()
            if int(matches[0]) < level:
                self.backup()
                return (mrel,frel)
            # FTW
            elif matches[1] == "_FREL":
                if matches[2].lower() != "natural":
                    frel = matches[2].capitalize()
            # FTW
            elif matches[1] == "_MREL":
                if matches[2].lower() != "natural":
                    mrel = matches[2]
            elif matches[1] == "ADOP":
                mrel = "Adopted"
                frel = "Adopted"
            # Legacy
            elif matches[1] == "_STAT":
                mrel = matches[2]
                frel = matches[2]
            # Legacy _PREF
            elif matches[1][0] == "_":
                pass
            else:
                self.barf(level+1)
        return None
    
    def parse_family(self):
        self.addr = None
        note = ""
        while 1:
            matches = self.get_next()

            if int(matches[0]) == 0:
                self.backup()
                return
            elif matches[1] == "HUSB":
                gid = matches[2]
                handle = self.find_person_handle(self.map_gid(gid[1:-1]))
                self.family.set_father_handle(handle)
                self.ignore_sub_junk(2)
            elif matches[1] == "WIFE":
                gid = matches[2]
                handle = self.find_person_handle(self.map_gid(gid[1:-1]))
                self.family.set_mother_handle(handle)
                self.ignore_sub_junk(2)
            elif matches[1] == "SLGS":
                lds_ord = RelLib.LdsOrd()
                self.family.set_lds_sealing(lds_ord)
                self.parse_ord(lds_ord,2)
            elif matches[1] == "ADDR":
                self.addr = RelLib.Address()
                self.addr.set_street(matches[2] + self.parse_continue_data(1))
                self.parse_address(self.addr,2)
            elif matches[1] == "CHIL":
                mrel,frel = self.parse_ftw_relations(2)
                gid = matches[2]
                child = self.find_or_create_person(self.map_gid(gid[1:-1]))
                self.family.add_child_handle(child.get_handle())

                for f in child.get_parent_family_handle_list():
                    if f[0] == self.family.get_handle():
                        break
                else:
                    if (mrel=="Birth" or mrel=="") and (frel=="Birth" or frel==""):
                        child.set_main_parent_family_handle(self.family.get_handle())
                    else:
                        if child.get_main_parents_family_handle() == self.family:
                            child.set_main_parent_family_handle(None)
                    child.add_parent_family_handle(self.family.get_handle(),mrel,frel)
                    self.db.commit_person(child, self.trans)
            elif matches[1] == "NCHI":
                a = RelLib.Attribute()
                a.set_type("Number of Children")
                a.set_value(matches[2])
                self.family.add_attribute(a)
            elif matches[1] in ["RIN", "SUBM", "REFN","CHAN","SOUR"]:
                self.ignore_sub_junk(2)
            elif matches[1] == "OBJE":
                if matches[2] and matches[2][0] == '@':
                    self.barf(2)
                else:
                    self.parse_family_object(2)
            elif matches[1] == "_COMM":
                note = matches[2].strip() + self.parse_continue_data(1)
                self.family.set_note(note)
                self.ignore_sub_junk(2)
            elif matches[1] == "NOTE":
                note = self.parse_note(matches,self.family,1,note)
            else:
                event = RelLib.Event()
                try:
                    event.set_name(ged2fam[matches[1]])
                except:
                    event.set_name(matches[1])
                if event.get_name() == "Marriage":
                    self.family.set_relationship(RelLib.Family.MARRIED)
                self.db.add_event(event,self.trans)
                self.family.add_event_handle(event.get_handle())
                self.parse_family_event(event,2)
                self.db.commit_event(event, self.trans)
                del event

    def parse_note_base(self,matches,obj,level,old_note,task):
        note = old_note
        if matches[2] and matches[2][0] == "@":
            if self.nmap.has_key(matches[2]):
                self.share_note.append(obj)
                obj.set_note_object(self.nmap[matches[2]])
            else:
                noteobj = RelLib.Note()
                self.nmap[matches[2]] = noteobj
                self.share_note.append(obj)
                obj.set_note_object(noteobj)
        else:
            if old_note:
                note = "%s\n%s%s" % (old_note,matches[2],self.parse_continue_data(level))
            else:
                note = matches[2] + self.parse_continue_data(level)
            task(note)
            self.ignore_sub_junk(level+1)
        return note
        
    def parse_note(self,matches,obj,level,old_note):
        return self.parse_note_base(matches,obj,level,old_note,obj.set_note)

    def parse_comment(self,matches,obj,level,old_note):
        return self.parse_note_base(matches,obj,level,old_note,obj.set_comments)

    def parse_individual(self):
        name_cnt = 0
        note = ""
        while 1:
            matches = self.get_next()

            if int(matches[0]) == 0:
                self.backup()
                return
            elif matches[1] == "NAME":
                name = RelLib.Name()
                m = snameRegexp.match(matches[2])
                if m:
                    n = m.groups()[0]
                    n2 = m.groups()[1]
                    names = (n2,'',n,'','')
                else:
                    try:
                        names = nameRegexp.match(matches[2]).groups()
                    except:
                        names = (matches[2],"","","","")
                if names[0]:
                    name.set_first_name(names[0].strip())
                if names[2]:
                    name.set_surname(names[2].strip())
                if names[4]:
                    name.set_suffix(names[4].strip())
                if name_cnt == 0:
                    self.person.set_primary_name(name)
                else:
                    self.person.add_alternate_name(name)
                name_cnt = name_cnt + 1
                self.parse_name(name,2)
            elif matches[1] in ["ALIA","_ALIA"]:
                aka = RelLib.Name()
                try:
                    names = nameRegexp.match(matches[2]).groups()
                except:
                    names = (matches[2],"","","","")
                if names[0]:
                    aka.set_first_name(names[0])
                if names[2]:
                    aka.set_surname(names[2])
                if names[4]:
                    aka.set_suffix(names[4])
                self.person.add_alternate_name(aka)
            elif matches[1] == "OBJE":
                if matches[2] and matches[2][0] == '@':
                    self.barf(2)
                else:
                    self.parse_person_object(2)
            elif matches[1] in ["NOTE","_COMM"]:
                note = self.parse_note(matches,self.person,1,note)
            elif matches[1] == "SEX":
                if matches[2] == '':
                    self.person.set_gender(RelLib.Person.unknown)
                elif matches[2][0] == "M":
                    self.person.set_gender(RelLib.Person.male)
                else:
                    self.person.set_gender(RelLib.Person.female)
            elif matches[1] in [ "BAPL", "ENDL", "SLGC" ]:
                lds_ord = RelLib.LdsOrd()
                if matches[1] == "BAPL":
                    self.person.set_lds_baptism(lds_ord)
                elif matches[1] == "ENDL":
                    self.person.set_lds_endowment(lds_ord)
                else:
                    self.person.set_lds_sealing(lds_ord)
                self.parse_ord(lds_ord,2)
            elif matches[1] == "FAMS":
                handle = self.find_family_handle(matches[2][1:-1])
                self.person.add_family_handle(handle)
                if note == "":
                    note = self.parse_optional_note(2)
                else:
                    note = "%s\n\n%s" % (note,self.parse_optional_note(2))
            elif matches[1] == "FAMC":
                ftype,note = self.parse_famc_type(2)
                handle = self.find_family_handle(matches[2][1:-1])
                
                for f in self.person.get_parent_family_handle_list():
                    if f[0] == handle:
                        break
                else:
                    if ftype == "" or ftype == "Birth":
                        if self.person.get_main_parents_family_handle() == None:
                            self.person.set_main_parent_family_handle(handle)
                        else:
                            self.person.add_parent_family_handle(handle,"Unknown","Unknown")
                    else:
                        if self.person.get_main_parents_family_handle() == handle:
                            self.person.set_main_parent_family_handle(None)
                        self.person.add_parent_family_handle(handle,ftype,ftype)
            elif matches[1] == "RESI":
                addr = RelLib.Address()
                self.person.add_address(addr)
                self.parse_residence(addr,2)
            elif matches[1] == "ADDR":
                addr = RelLib.Address()
                addr.set_street(matches[2] + self.parse_continue_data(1))
                self.parse_address(addr,2)
                self.person.add_address(addr)
            elif matches[1] == "PHON":
                addr = RelLib.Address()
                addr.set_street("Unknown")
                addr.set_phone(matches[2])
                self.person.add_address(addr)
            elif matches[1] == "BIRT":
                event = RelLib.Event()
                self.db.add_event(event, self.trans)
                if self.person.get_birth_handle():
                    event.set_name("Alternate Birth")
                    self.person.add_event_handle(event.get_handle())
                else:
                    event.set_name("Birth")
                    self.person.set_birth_handle(event.get_handle())
                self.parse_person_event(event,2)
                self.db.commit_event(event, self.trans)
            elif matches[1] == "ADOP":
                event = RelLib.Event()
                event.set_name("Adopted")
                self.person.add_event_handle(event.get_handle())
                self.parse_adopt_event(event,2)
                self.db.add_event(event, self.trans)
            elif matches[1] == "DEAT":
                event = RelLib.Event()
                self.db.add_event(event, self.trans)
                if self.person.get_death_handle():
                    event.set_name("Alternate Death")
                    self.person.add_event_handle(event.get_handle())
                else:
                    event.set_name("Death")
                    self.person.set_death_handle(event.get_handle())
                self.parse_person_event(event,2)
                self.db.commit_event(event, self.trans)
            elif matches[1] == "EVEN":
                event = RelLib.Event()
                if matches[2]:
                    event.set_description(matches[2])
                self.parse_person_event(event,2)
                n = event.get_name().strip() 
                if n in self.attrs:
                    attr = RelLib.Attribute()
                    attr.set_type(self.gedattr[n])
                    attr.set_value(event.get_description())
                    self.person.add_attribute(attr)
                else:
                    self.db.add_event(event, self.trans)
                    self.person.add_event_handle(event.get_handle())
            elif matches[1] == "SOUR":
                source_ref = self.handle_source(matches,2)
                self.person.add_source_reference(source_ref)
            elif matches[1] == "REFN":
                if intRE.match(matches[2]):
                    try:
                        self.refn[self.person.get_handle()] = int(matches[2])
                    except:
                        pass
            elif matches[1] in ["AFN","RFN","_UID"]:
                attr = RelLib.Attribute()
                attr.set_type(matches[1])
                attr.set_value(matches[2])
                self.person.add_attribute(attr)
            elif matches[1] in ["CHAN","ASSO","ANCI","DESI","RIN"]:
                self.ignore_sub_junk(2)
            else:
                event = RelLib.Event()
                n = matches[1].strip()
                if ged2gramps.has_key(n):
                    event.set_name(ged2gramps[n])
                elif self.gedattr.has_key(n):
                    attr = RelLib.Attribute()
                    attr.set_type(self.gedattr[n])
                    attr.set_value(event.get_description())
                    self.person.add_attribute(attr)
                    self.parse_person_attr(attr,2)
                    continue
                else:
                    val = self.gedsource.tag2gramps(n)
                    if val:
                        event.set_name(val)
                    else:
                        event.set_name(n)
                    
                self.parse_person_event(event,2)
                if matches[2]:
                    event.set_description(matches[2])
                self.db.add_event(event, self.trans)
                self.person.add_event_handle(event.get_handle())
                
    def parse_optional_note(self,level):
        note = ""
        while 1:
            matches = self.get_next()

            if int(matches[0]) < level:
                self.backup()
                return note
            elif matches[1] == "NOTE":
                if not matches[2].strip() or matches[2] and matches[2][0] != "@":
                    note = matches[2] + self.parse_continue_data(level+1)
                    self.parse_note_data(level+1)
                else:
                    self.ignore_sub_junk(level+1)
            else:
                self.barf(level+1)
        return None
        
    def parse_famc_type(self,level):
        ftype = ""
        note = ""
        while 1:
            matches = self.get_next()

            if int(matches[0]) < level:
                self.backup()
                return (ftype.capitalize(),note)
            elif matches[1] == "PEDI":
                ftype = matches[2]
            elif matches[1] == "SOUR":
                source_ref = self.handle_source(matches,level+1)
                self.person.get_primary_name().add_source_reference(source_ref)
            elif matches[1] == "_PRIMARY":
                pass #type = matches[1]
            elif matches[1] == "NOTE":
                if not matches[2].strip() or matches[2] and matches[2][0] != "@":
                    note = matches[2] + self.parse_continue_data(level+1)
                    self.parse_note_data(level+1)
                else:
                    self.ignore_sub_junk(level+1)
            else:
                self.barf(level+1)
        return None
    
    def parse_person_object(self,level):
        form = ""
        filename = ""
        title = "no title"
        note = ""
        while 1:
            matches = self.get_next()
            if matches[1] == "FORM":
                form = string.lower(matches[2])
            elif matches[1] == "TITL":
                title = matches[2]
            elif matches[1] == "FILE":
                filename = matches[2]
            elif matches[1] == "NOTE":
                note = matches[2] + self.parse_continue_data(level+1)
            elif matches[1][0] == "_":
                self.ignore_sub_junk(level+1)
            elif int(matches[0]) < level:
                self.backup()
                break
            else:
                self.barf(level+1)

        if form == "url":
            url = RelLib.Url()
            url.set_path(filename)
            url.set_description(title)
            self.person.add_url(url)
        else:
            (ok,path) = self.find_file(filename,self.dir_path)
            if not ok:
                self.warn(_("Warning: could not import %s") % filename + "\n")
                self.warn(_("\tThe following paths were tried:\n\t\t"))
                self.warn(string.join(path,"\n\t\t"))
                self.warn('\n')
            else:
                photo_handle = self.media_map.get(path)
                if photo_handle == None:
                    photo = RelLib.MediaObject()
                    photo.set_path(path)
                    photo.set_description(title)
                    photo.set_mime_type(Utils.get_mime_type(path))
                    self.db.add_object(photo, self.trans)
                    self.media_map[path] = photo.get_handle()
                else:
                    photo = self.db.get_object_from_handle(photo_handle)
                oref = RelLib.MediaRef()
                oref.set_reference_handle(photo.get_handle())
                self.person.add_media_reference(oref)
                self.db.commit_person(self.person, self.trans)

    def parse_family_object(self,level):
        form = ""
        filename = ""
        title = ""
        note = ""
        while 1:
            matches = self.get_next()
            if matches[1] == "FORM":
                form = string.lower(matches[2])
            elif matches[1] == "TITL":
                title = matches[2]
            elif matches[1] == "FILE":
                filename = matches[2]
            elif matches[1] == "NOTE":
                note = matches[2] + self.parse_continue_data(level+1)
            elif int(matches[0]) < level:
                self.backup()
                break
            else:
                self.barf(level+1)
                
        if form:
            (ok,path) = self.find_file(filename,self.dir_path)
            if not ok:
                self.warn(_("Warning: could not import %s") % filename + "\n")
                self.warn(_("\tThe following paths were tried:\n\t\t"))
                self.warn(string.join(path,"\n\t\t"))
                self.warn('\n')
            else:
                photo = RelLib.MediaObject()
                photo.set_path(path)
                photo.set_description(title)
                photo.set_mime_type(Utils.get_mime_type(path))
                self.db.add_object(photo, self.trans)
                oref = RelLib.MediaRef()
                oref.set_reference_handle(photo.get_handle())
                self.family.add_media_reference(photo)
                self.db.commit_family(self.family, self.trans)

    def parse_residence(self,address,level):
        note = ""
        while 1:
            matches = self.get_next()

            if int(matches[0]) < level:
                self.backup()
                return 
            elif matches[1] == "DATE":
                address.set_date_object(self.extract_date(matches[2]))
            elif matches[1] == "ADDR":
                address.set_street(matches[2] + self.parse_continue_data(level+1))
                self.parse_address(address,level+1)
            elif matches[1] in ["AGE","AGNC","CAUS","STAT","TEMP","OBJE","TYPE","_DATE2"]:
                self.ignore_sub_junk(level+1)
            elif matches[1] == "SOUR":
                address.add_source_reference(self.handle_source(matches,level+1))
            elif matches[1] == "PLAC":
                address.set_street(matches[2])
                self.parse_address(address,level+1)
            elif matches[1] == "PHON":
                address.set_street("Unknown")
                address.set_phone(matches[2])
            elif matches[1] == "NOTE":
                note = self.parse_note(matches,address,level+1,note)
            else:
                self.barf(level+1)

    def parse_address(self,address,level):
        first = 0
        note = ""
        while 1:
            matches = self.get_next()
            if int(matches[0]) < level:
                if matches[1] == "PHON":
                    address.set_phone(matches[2])
                else:
                    self.backup()
                return
            elif matches[1] in [ "ADDR", "ADR1", "ADR2" ]:
                val = address.get_street()
                data = self.parse_continue_data(level+1)
                if first == 0:
                    val = "%s %s" % (matches[2],data)
                    first = 1
                else:
                    val = "%s,%s %s" % (val,matches[2],data)
                address.set_street(val)
            elif matches[1] == "CITY":
                address.set_city(matches[2])
            elif matches[1] == "STAE":
                address.set_state(matches[2])
            elif matches[1] == "POST":
                address.set_postal_code(matches[2])
            elif matches[1] == "CTRY":
                address.set_country(matches[2])
            else:
                self.barf(level+1)

    def parse_ord(self,lds_ord,level):
        note = ""
        while 1:
            matches = self.get_next()
            if int(matches[0]) < level:
                self.backup()
                break
            elif matches[1] == "TEMP":
                value = extract_temple(matches)
                if value:
                    lds_ord.set_temple(value)
            elif matches[1] == "DATE":
                lds_ord.set_date_object(self.extract_date(matches[2]))
            elif matches[1] == "FAMC":
                lds_ord.set_family_handle(self.find_family_handle(matches[2][1:-1]))
            elif matches[1] == "PLAC":
              try:
                place = self.find_or_create_place(matches[2])
                place.set_title(matches[2])
                place_handle = place.get_handle()
                lds_ord.set_place_handle(place_handle)
                self.ignore_sub_junk(level+1)
              except NameError:
                  pass
            elif matches[1] == "SOUR":
                lds_ord.add_source_reference(self.handle_source(matches,level+1))
            elif matches[1] == "NOTE":
                note = self.parse_note(matches,lds_ord,level+1,note)
            elif matches[1] == "STAT":
                if const.lds_status.has_key(matches[2]):
                    lds_ord.set_status(const.lds_status[matches[2]])
            else:
                self.barf(level+1)

    def parse_person_event(self,event,level):
        note = ""
        while 1:
            matches = self.get_next()
            if int(matches[0]) < level:
                if note:
                    event.set_note(note)
                self.backup()
                break
            elif matches[1] == "TYPE":
                if event.get_name() == "":
                    if ged2gramps.has_key(matches[2]):
                        name = ged2gramps[matches[2]]
                    else:
                        val = self.gedsource.tag2gramps(matches[2])
                        if val:
                            name = val
                        else:
                            name = matches[2]
                    event.set_name(name)
                else:
                    event.set_description(matches[2])
            elif matches[1] == "DATE":
                event.set_date_object(self.extract_date(matches[2]))
            elif matches[1] == "SOUR":
                event.add_source_reference(self.handle_source(matches,level+1))
            elif matches[1] == "PLAC":
                val = matches[2]
                n = string.strip(event.get_name())
                if self.is_ftw and n in ["Occupation","Degree","SSN"]:
                    event.set_description(val)
                    self.ignore_sub_junk(level+1)
                else:
                    place = self.find_or_create_place(val)
                    place_handle = place.get_handle()
                    place.set_title(matches[2])
                    event.set_place_handle(place_handle)
                    self.ignore_sub_junk(level+1)
            elif matches[1] == "CAUS":
                info = matches[2] + self.parse_continue_data(level+1)
                event.set_cause(info)
                self.parse_cause(event,level+1)
            elif matches[1] == "NOTE" or matches[1] == 'OFFI':
                info = matches[2] + self.parse_continue_data(level+1)
                if note == "":
                    note = info
                else:
                    note = "\n%s" % info
            elif matches[1] == "CONC":
                d = event.get_description()
                if self.broken_conc:
                    event.set_description("%s %s" % (d, matches[2]))
                else:
                    event.set_description("%s%s" % (d, matches[2]))
            elif matches[1] == "CONT":
                event.set_description("%s\n%s" % (event.get_description(),matches[2]))
            elif matches[1] in ["RELI", "TIME","ADDR","AGE","AGNC","STAT","TEMP","OBJE","_DATE2"]:
                self.ignore_sub_junk(level+1)
            else:
                self.barf(level+1)

    def parse_adopt_event(self,event,level):
        note = ""
        while 1:
            matches = self.get_next()
            if int(matches[0]) < level:
                if note != "":
                    event.set_note(note)
                self.backup()
                break
            elif matches[1] == "DATE":
                event.set_date_object(self.extract_date(matches[2]))
            elif matches[1] in ["TIME","ADDR","AGE","AGNC","STAT","TEMP","OBJE"]:
                self.ignore_sub_junk(level+1)
            elif matches[1] == "SOUR":
                event.add_source_reference(self.handle_source(matches,level+1))
            elif matches[1] == "FAMC":
                handle = self.find_family_handle(matches[2][1:-1])
                mrel,frel = self.parse_adopt_famc(level+1);
                if self.person.get_main_parents_family_handle() == handle:
                    self.person.set_main_parent_family_handle(None)
                self.person.add_parent_family_handle(handle,mrel,frel)
            elif matches[1] == "PLAC":
                val = matches[2]
                place = self.find_or_create_place(val)
                place_handle = place.get_handle()
                place.set_title(matches[2])
                event.set_place_handle(place_handle)
                self.ignore_sub_junk(level+1)
            elif matches[1] == "TYPE":
                # eventually do something intelligent here
                pass
            elif matches[1] == "CAUS":
                info = matches[2] + self.parse_continue_data(level+1)
                event.set_cause(info)
                self.parse_cause(event,level+1)
            elif matches[1] == "NOTE":
                info = matches[2] + self.parse_continue_data(level+1)
                if note == "":
                    note = info
                else:
                    note = "\n%s" % info
            elif matches[1] == "CONC":
                d = event.get_description()
                if self.broken_conc:
                    event.set_description("%s %s" % (d,matches[2]))
                else:
                    event.set_description("%s%s" % (d,matches[2]))
            elif matches[1] == "CONT":
                d = event.get_description()
                event.set_description("%s\n%s" % (d,matches[2]))
            else:
                self.barf(level+1)

    def parse_adopt_famc(self,level):
        mrel = "Adopted"
        frel = "Adopted"
        while 1:
            matches = self.get_next()
            if int(matches[0]) < level:
                self.backup()
                return (mrel,frel)
            elif matches[1] == "ADOP":
                if matches[2] == "HUSB":
                    mrel = "Birth"
                elif matches[2] == "WIFE":
                    frel = "Birth"
            else:
                self.barf(level+1)
        return None
    
    def parse_person_attr(self,attr,level):
        note = ""
        while 1:
            matches = self.get_next()
            if int(matches[0]) < level:
                self.backup()
                break
            elif matches[1] == "TYPE":
                if attr.get_type() == "":
                    if ged2gramps.has_key(matches[2]):
                        name = ged2gramps[matches[2]]
                    else:
                        val = self.gedsource.tag2gramps(matches[2])
                        if val:
                            name = val
                        else:
                            name = matches[2]
                    attr.set_name(name)
            elif matches[1] in ["CAUS", "DATE","TIME","ADDR","AGE","AGNC","STAT","TEMP","OBJE"]:
                self.ignore_sub_junk(level+1)
            elif matches[1] == "SOUR":
                attr.add_source_reference(self.handle_source(matches,level+1))
            elif matches[1] == "PLAC":
                val = matches[2]
                if attr.get_value() == "":
                    attr.set_value(val)
                    self.ignore_sub_junk(level+1)
            elif matches[1] == "DATE":
                note = "%s\n\n" % ("Date : %s" % matches[2])
            elif matches[1] == "NOTE":
                info = matches[2] + self.parse_continue_data(level+1)
                if note == "":
                    note = info
                else:
                    note = "%s\n\n%s" % (note,info)
            elif matches[1] == "CONC":
                if self.broken_conc:
                    attr.set_value("%s %s" % (attr.get_value(), matches[2]))
                else:
                    attr.set_value("%s %s" % (attr.get_value(), matches[2]))
            elif matches[1] == "CONT":
                attr.set_value("%s\n%s" % (attr.get_value(),matches[2]))
            else:
                self.barf(level+1)
        if note != "":
            attr.set_note(note)

    def parse_family_event(self,event,level):
        note = ""
        while 1:
            matches = self.get_next()
            if int(matches[0]) < level:
                if note:
                    event.set_note(note)
                self.backup()
                break
            elif matches[1] == "TYPE":
                if event.get_name() == "" or event.get_name() == 'EVEN': 
                    try:
                        event.set_name(ged2fam[matches[2]])
                    except:
                        event.set_name(matches[2])
                else:
                    note = 'Status = %s\n' % matches[2]
            elif matches[1] == "DATE":
                event.set_date_object(self.extract_date(matches[2]))
            elif matches[1] == "CAUS":
                info = matches[2] + self.parse_continue_data(level+1)
                event.set_cause(info)
                self.parse_cause(event,level+1)
            elif matches[1] in ["TIME","AGE","AGNC","ADDR","STAT",
                                "TEMP","HUSB","WIFE","OBJE","_CHUR"]:
                self.ignore_sub_junk(level+1)
            elif matches[1] == "SOUR":
                event.add_source_reference(self.handle_source(matches,level+1))
            elif matches[1] == "PLAC":
                val = matches[2]
                place = self.find_or_create_place(val)
                place_handle = place.get_handle()
                place.set_title(matches[2])
                event.set_place_handle(place_handle)
                self.ignore_sub_junk(level+1)
            elif matches[1] == 'OFFI':
                if note == "":
                    note = matches[2]
                else:
                    note = note + "\n" + matches[2]
            elif matches[1] == "NOTE":
                note = self.parse_note(matches,event,level+1,note)
            else:
                self.barf(level+1)

    def parse_source_reference(self,source,level):
        """Reads the data associated with a SOUR reference"""
        note = ""
        while 1:
            matches = self.get_next()

            if int(matches[0]) < level:
                self.backup()
                return
            elif matches[1] == "PAGE":
                source.set_page(matches[2] + self.parse_continue_data(level+1))
            elif matches[1] == "DATA":
                date,text = self.parse_source_data(level+1)
                d = self.dp.parse(date)
                source.set_date(d)
                source.set_text(text)
            elif matches[1] in ["OBJE","REFN","TEXT"]:
                self.ignore_sub_junk(level+1)
            elif matches[1] == "QUAY":
                val = int(matches[2])
                if val > 1:
                    source.set_confidence_level(val+1)
                else:
                    source.set_confidence_level(val)
            elif matches[1] == "NOTE":
                note = self.parse_comment(matches,source,level+1,note)
            else:
                self.barf(level+1)
        
    def parse_source_data(self,level):
        """Parses the source data"""
        date = ""
        note = ""
        while 1:
            matches = self.get_next()
            if int(matches[0]) < level:
                self.backup()
                return (date,note)
            elif matches[1] == "DATE":
                date = matches[2]
            elif matches[1] == "TEXT":
                note = matches[2] + self.parse_continue_data(level+1)
            else:
                self.barf(level+1)
        return None
    
    def parse_name(self,name,level):
        """Parses the person's name information"""
        note = ""
        while 1:
            matches = self.get_next()
            if int(matches[0]) < level:
                self.backup()
                return
            elif matches[1] in ["ALIA","_ALIA"]:
                aka = RelLib.Name()
                try:
                    names = nameRegexp.match(matches[2]).groups()
                except:
                    names = (matches[2],"","","","")
                if names[0]:
                    aka.set_first_name(names[0])
                if names[2]:
                    aka.set_surname(names[2])
                if names[4]:
                    aka.set_suffix(names[4])
                self.person.add_alternate_name(aka)
            elif matches[1] == "NPFX":
                name.set_title(matches[2])
            elif matches[1] == "GIVN":
                name.set_first_name(matches[2])
            elif matches[1] == "SPFX":
                name.set_surname_prefix(matches[2])
            elif matches[1] == "SURN":
                name.set_surname(matches[2])
            elif matches[1] == "_MARNM":
                self.parse_marnm(self.person,matches[2].strip())
            elif matches[1] == "TITL":
                name.set_suffix(matches[2])
            elif matches[1] == "NSFX":
                if name.get_suffix() == "":
                    name.set_suffix(matches[2])
            elif matches[1] == "NICK":
                self.person.set_nick_name(matches[2])
            elif matches[1] == "_AKA":
                lname = string.split(matches[2])
                l = len(lname)
                if l == 1:
                    self.person.set_nick_name(matches[2])
                else:
                    name = RelLib.Name()
                    name.set_surname(lname[-1])
                    name.set_first_name(string.join(lname[0:l-1]))
                    self.person.add_alternate_name(name)
            elif matches[1] == "SOUR":
                name.add_source_reference(self.handle_source(matches,level+1))
            elif matches[1][0:4] == "NOTE":
                note = self.parse_note(matches,name,level+1,note)
            else:
                self.barf(level+1)

    def parse_marnm(self,person,text):
        data = text.split()
        if len(data) == 1:
            name = RelLib.Name(person.get_primary_name())
            name.set_surname(data[0])
            name.set_type('Married Name')
            person.add_alternate_name(name)
        elif len(data) > 1:
            name = RelLib.Name()
            name.set_surname(data[-1])
            name.set_first_name(string.join(data[0:-1],' '))
            name.set_type('Married Name')
            person.add_alternate_name(name)

    def parse_header_head(self):
        """validiates that this is a valid GEDCOM file"""
        line = string.replace(self.f.readline(),'\r','')
        match = headRE.search(line)
        if not match:
            raise Errors.GedcomError("%s is not a GEDCOM file" % self.filename)
        self.index = self.index + 1

    def parse_header_source(self):
        genby = ""
        while 1:
            matches = self.get_next()

            if int(matches[0]) == 0:
                self.backup()
                return
            elif matches[1] == "SOUR":
                if self.window and self.created_obj.get_text():
                    self.update(self.created_obj,matches[2])
                self.gedsource = self.gedmap.get_from_source_tag(matches[2])
                self.broken_conc = self.gedsource.get_conc()
                if matches[2] == "FTW":
                    self.is_ftw = 1
                genby = matches[2]
            elif matches[1] == "NAME" and self.window:
                self.update(self.created_obj,matches[2])
            elif matches[1] == "VERS" and self.window:
                self.def_src.set_data_item('Generated by',"%s %s" %
                                                  (genby,matches[2]))
                self.update(self.version_obj,matches[2])
                pass
            elif matches[1] == "FILE":
                filename = os.path.basename(matches[2]).split('\\')[-1]
                self.def_src.set_title(_("Import from %s") % unicode(filename))
            elif matches[1] == "COPR":
                self.def_src.set_publication_info(unicode(matches[2]))
            elif matches[1] in ["CORP","DATA","SUBM","SUBN","LANG"]:
                self.ignore_sub_junk(2)
            elif matches[1] == "DEST":
                if genby == "GRAMPS":
                    self.gedsource = self.gedmap.get_from_source_tag(matches[2])
                    self.broken_conc = self.gedsource.get_conc()
            elif matches[1] == "CHAR" and not self.override:
                if matches[2] == "UNICODE" or matches[2] == "UTF-8" or matches[2] == "UTF8":
                    self.cnv = nocnv
                elif matches[2] == "ANSEL":
                    self.cnv = ansel_to_utf8
                else:
                    self.cnv = latin_utf8.latin_to_utf8
                self.ignore_sub_junk(2)
                if self.window:
                    self.update(self.encoding_obj,matches[2])
                else:
                    self.update(self.encoding_obj,_("Overridden"))
            elif matches[1] == "GEDC":
                self.ignore_sub_junk(2)
            elif matches[1] == "_SCHEMA":
                self.parse_ftw_schema(2)
            elif matches[1] == "PLAC":
                self.parse_place_form(2)
            elif matches[1] == "DATE":
                date = self.parse_date(2)
                date.date = matches[2]
                self.def_src.set_data_item('Creation date',unicode(matches[2]))
            elif matches[1] == "NOTE":
                note = matches[2] + self.parse_continue_data(2)
            elif matches[1][0] == "_":
                self.ignore_sub_junk(2)
            else:
                self.barf(2)

    def parse_ftw_schema(self,level):
        while 1:
            matches = self.get_next()

            if int(matches[0]) < level:
                self.backup()
                return
            elif matches[1] == "INDI":
                self.parse_ftw_indi_schema(level+1)
            elif matches[1] == "FAM":
                self.parse_ftw_fam_schema(level+1)
            else:
                self.barf(2)

    def parse_ftw_indi_schema(self,level):
        while 1:
            matches = self.get_next()

            if int(matches[0]) < level:
                self.backup()
                return
            else:
                label = self.parse_label(level+1)
                ged2gramps[matches[1]] = label

    def parse_label(self,level):
        while 1:
            matches = self.get_next()

            if int(matches[0]) < level:
                self.backup()
                return
            elif matches[1] == "LABL":
                return matches[2]
            else:
                self.barf(2)
        return None
    
    def parse_ftw_fam_schema(self,level):
        while 1:
            matches = self.get_next()

            if int(matches[0]) < level:
                self.backup()
                return
            else:
                label = self.parse_label(level+1)
                ged2fam[matches[1]] = label
        return None
    
    def ignore_sub_junk(self,level):
        while 1:
            matches = self.get_next()
            if int(matches[0]) < level:
                self.backup()
                return
        return
    
    def ignore_change_data(self,level):
        matches = self.get_next()
        if matches[1] == "CHAN":
            self.ignore_sub_junk(level+1)
        else:
            self.backup()

    def parse_place_form(self,level):
        while 1:
            matches = self.get_next()

            if int(matches[0]) < level:
                self.backup()
                return
            elif matches[1] != "FORM":
                self.barf(level+1)
    
    def parse_continue_data(self,level):
        data = ""
        while 1:
            matches = self.get_next()

            if int(matches[0]) < level:
                self.backup()
                return data
            elif matches[1] == "CONC":
                if self.broken_conc:
                    data = "%s %s" % (data,matches[2])
                else:
                    data = "%s%s" % (data,matches[2])
            elif matches[1] == "CONT":
                data = "%s\n%s" % (data,matches[2])
            else:
                self.backup()
                return data
        return None
    
    def parse_note_continue(self,level):
        data = ""
        while 1:
            matches = self.get_next()

            if int(matches[0]) < level:
                self.backup()
                return data
            elif matches[1] == "NOTE":
                data = "%s\n%s%s" % (data,matches[2],self.parse_continue_data(level+1))
            elif matches[1] == "CONC":
                if self.broken_conc:
                    data = "%s %s" % (data,matches[2])
                else:
                    data = "%s%s" % (data,matches[2])
            elif matches[1] == "CONT":
                data = "%s\n%s" % (data,matches[2])
            else:
                self.backup()
                return data
        return None

    def parse_date(self,level):
        date = DateStruct()
        while 1:
            matches = self.get_next()

            if int(matches[0]) < level:
                self.backup()
                return date
            elif matches[1] == "TIME":
                date.time = matches[2]
            else:
                self.barf(level+1)
        return None

    def extract_date(self,text):
        dateobj = Date.Date()
        try:
            match = rangeRegexp.match(text)
            if match:
                (cal1,data1,cal2,data2) = match.groups()
                if cal1 != cal2:
                    pass
                
                if cal1 == "FRENCH R":
                    cal = Date.CAL_FRENCH
                elif cal1 == "JULIAN":
                    cal = Date.CAL_JULIAN
                elif cal1 == "HEBREW":
                    cal = Date.CAL_HEBREW
                else:
                    cal = Date.CAL_GREGORIAN
                    
                start = self.dp.parse(data1)
                stop =  self.dp.parse(data2)
                dateobj.set(Date.QUAL_NONE, Date.MOD_RANGE, cal,
                            start.get_start_date() + stop.get_start_date())
                return dateobj

            match = spanRegexp.match(text)
            if match:
                (cal1,data1,cal2,data2) = match.groups()
                if cal1 != cal2:
                    pass
                
                if cal1 == "FRENCH R":
                    cal = Date.CAL_FRENCH
                elif cal1 == "JULIAN":
                    cal = Date.CAL_JULIAN
                elif cal1 == "HEBREW":
                    cal = Date.CAL_HEBREW
                else:
                    cal = Date.CAL_GREGORIAN
                    
                start = self.dp.parse(data1)
                stop =  self.dp.parse(data2)
                dateobj.set(Date.QUAL_NONE, Date.MOD_SPAN, cal,
                            start.get_start_date() + stop.get_start_date())
                return dateobj
        
            match = calRegexp.match(text)
            if match:
                (abt,cal,data) = match.groups()
                dateobj = self.dp.parse("%s %s" % (abt, data))
                if cal == "FRENCH R":
                    dateobj.set_calendar(Date.CAL_FRENCH)
                elif cal == "JULIAN":
                    dateobj.set_calendar(Date.CAL_JULIAN)
                elif cal == "HEBREW":
                    dateobj.set_calendar(Date.CAL_HEBREW)
                return dateobj
            else:
                dval = self.dp.parse(text)
                return dval
        except IOError:
            return self.dp.set_text(text)

    def handle_source(self,matches,level):
        source_ref = RelLib.SourceRef()
        if matches[2] and matches[2][0] != "@":
            self.localref = self.localref + 1
            ref = "gsr%d" % self.localref
            s = self.find_or_create_source(ref)
            source_ref.set_base_handle(s.get_handle())
            s.set_title('Imported Source #%d' % self.localref)
            s.set_note(matches[2] + self.parse_continue_data(level))
            self.ignore_sub_junk(level+1)
        else:
            source_ref.set_base_handle(self.find_or_create_source(matches[2][1:-1]).get_handle())
            self.parse_source_reference(source_ref,level)
        return source_ref

    def resolve_refns(self):
        return
    
        prefix = self.db.iprefix
        index = 0
        new_pmax = self.db.pmap_index
        for pid in self.added.keys():
            index = index + 1
            if self.refn.has_key(pid):
                val = self.refn[pid]
                new_key = prefix % val
                new_pmax = max(new_pmax,val)

                person = self.db.get_person_from_handle(pid,self.trans)

                # new ID is not used
                if not self.db.has_person_handle(new_key):
                    self.db.remove_person(pid,self.trans)
                    person.set_handle(new_key)
                    person.set_gramps_id(new_key)
                    self.db.add_person(person,self.trans)
                else:
                    tp = self.db.get_person_from_handle(new_key,self.trans)
                    # same person, just change it
                    if person == tp:
                        self.db.remove_person(pid,self.trans)
                        person.set_handle(new_key)
                        person.set_gramps_id(new_key)
                        self.db.add_person(person,self.trans)
                    # give up trying to use the refn as a key
                    else:
                        pass

        self.db.pmap_index = new_pmax

    def invert_year(self,subdate):
        return (subdate[0],subdate[1],-subdate[2],subdate[3])
    
    def parse(self,text):
        """
        Parses the text, returning a Date object.
        """
        new_date = Date.Date()
        self.set_date(new_date,text)
        return new_date

def extract_temple(matches):
    try:
        if const.lds_temple_to_abrev.has_key(matches[2]):
            return const.lds_temple_to_abrev[matches[2]]
        else:
            values = matches[2].split()
            return const.lds_temple_to_abrev[values[0]]
    except:
        return None

#-------------------------------------------------------------------------
#
#
#
#-------------------------------------------------------------------------
def readData(database,active_person,cb):
    global callback
    global file_topa
    
    callback = cb

    choose = gtk.FileChooserDialog("%s - GRAMPS" % _title_string,
                                   None,
                                   gtk.FILE_CHOOSER_ACTION_OPEN,
                                   (gtk.STOCK_CANCEL,
                                    gtk.RESPONSE_CANCEL,
                                    gtk.STOCK_OPEN,
                                    gtk.RESPONSE_OK))
    mime_filter = gtk.FileFilter()
    mime_filter.set_name(_('GEDCOM files'))
    mime_filter.add_pattern('*.ged')
    mime_filter.add_pattern('*.GED')
    choose.add_filter(mime_filter)
        
    mime_filter = gtk.FileFilter()
    mime_filter.set_name(_('All files'))
    mime_filter.add_pattern('*')
    choose.add_filter(mime_filter)

    response = choose.run()
    if response == gtk.RESPONSE_OK:
        filename = choose.get_filename()
        choose.destroy()
        try:
            importData(database,filename)
        except:
            import DisplayTrace
            DisplayTrace.DisplayTrace()
    else:
        choose.destroy()


_mime_type = 'application/x-gedcom'
_filter = gtk.FileFilter()
_filter.set_name(_('GEDCOM files'))
_filter.add_mime_type(_mime_type)


#-------------------------------------------------------------------------
#
#
#
#-------------------------------------------------------------------------
def create_id():
    return Utils.create_id()

#-------------------------------------------------------------------------
#
#
#
#-------------------------------------------------------------------------
from Plugins import register_import
register_import(importData,_filter,_mime_type,1)
