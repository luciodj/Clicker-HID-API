#!usr/bin/python
#
# HIDBootloader for PIC18 CLicker board series 
# 
# Author: Lucio Di Jasio
# url: blog.flyingpic24.com
#
import hid
import time
import sys
import subprocess
import intelhex
from Tkinter import *
from tkFileDialog import askopenfilename

__version__ = 0.1

MikroE_vid = 0x1234
Mikromedia_pid = 1

Microchip_vid = 0x4d8
Clicker_pid = 0x3f      # same as Custom HID demo board

STX         = 0x0F
cmdSYNC     =  1
cmdINFO     =  2
cmdBOOT     =  3
cmdREBOOT   =  4
cmdWRITE    = 11
cmdERASE    = 21

"""
Protocol Description.

    USB protocol is a typical master-slave communication protocol, where
    master (PC) sends commands and slave (bootloader equipped device) executes
    them and acknowledges execution.

    * Command format.
    
    <STX[0]><CMD_CODE[0]><ADDRESS[0..3]><COUNT[0..1]> <DATA[0..COUNT-1]>
    |-- 1 --|---- 1 -----|------ 4 -----|----- 2 ----|------ COUNT -----|

    STX      - Command start delimiter (for future upgrades).
               Length: 1 byte. Mandatory.
    CMD_CODE - Command index (TCmd).
               Length: 1 byte. Mandatory.
    ADDRESS  - Address field. Flash start address for
               CMD_CODE command operation.
               Length: 4 bytes. Optional (command specific).
    COUNT    - Count field. Amount of data/blocks for
               CMD_CODE command operation.
               Length: 2 bytes. Optional (command specific).
    DATA     - Data array.
               Length: COUNT bytes. Optional (command specific).

    Some commands do not utilize all of these fields.
    See 'Command Table' below for details on specific command's format.

    * Command Table.
     --------------------------+---------------------------------------------------
    |       Description        |                      Format                       |
    | Synchronize with PC tool |                  <STX><cmdSYNC>                   |
    | Send bootloader info     |                  <STX><cmdINFO>                   |
    | Go to bootloader mode    |                  <STX><cmdBOOT>                   |
    | Restart MCU              |                  <STX><cmdREBOOT>                 |
    | Write to MCU flash       | <STX><cmdWRITE><START_ADDR><DATA_LEN><DATA_ARRAY> |
    | Erase MCU flash.         |  <STX><cmdERASE><START_ADDR><ERASE_BLOCK_COUNT>   |
     ------------------------------------------------------------------------------ 
     
     * Acknowledge format.
   
    <STX[0]><CMD_CODE[0]>
    |-- 1 --|---- 1 -----|
   
    STX      - Response start delimiter (for future upgrades).
               Length: 1 byte. Mandatory.
    CMD_CODE - Index of command (TCmd) we want to acknowledge.
               Length: 1 byte. Mandatory.

    See 'Acknowledgement Table' below for details on specific command's 
    acknowledgement process.
    
    * Acknowledgement Table.
     --------------------------+---------------------------------------------------
    |       Description        |                   Acknowledgement                 |
    |--------------------------+---------------------------------------------------|
    | Synchronize with PC tool |                  upon reception                   |
    | Send bootloader info     |          no acknowledge, just send info           |
    | Go to bootloader mode    |                  upon reception                   |
    | Restart MCU              |                  no acknowledge                   |
    | Write to MCU flash       | upon each write of internal buffer data to flash  |
    | Erase MCU flash.         |                  upon execution                   |
   
"""
# Supported MCU families/types.
dMcuType = { "PIC16" : 1, 'PIC18':2, 'PIC18FJ':3, 'PIC24':4, 'dsPIC':10, 'PIC32': 20}

#define an INFO record
class info:
    McuType = ''
    McuId = 0
    McuSize = 0
    WriteBlock = 0
    EraseBlock = 0
    BootloaderRevision = 0
    DeviceDescription = ''
    BootStart = 0
    # additional fields 
    dHex = None


def align( index):
    if index & 1: 
        print "align to %d" % (index+1)
        return index+1
    else: 
        return index

def getMCUtype( list, i):
    for item in dMcuType.items():
        if item[1] == list[i]:
            info.McuType = item[0]
            print "MCU type is:", info.McuType
            return i
    print "MCU type (%d) not recognized" % list[i]
    return i

def skip_align( list, i):
    #print "skip", i
    return i

def getMCUid( list, i):
    # MCUId appears not to be used anymore, report error
    print 'MCUId Info field found!?'
    exit(1)   

def getMCUSIZE( list, i):
    low  = int(list[i+0]) + int(list[i+1])*256
    high = int(list[i+2]) + int(list[i+3])*256
    info.McuSize = high*65536 + low
    print "MCU size = %d" % info.McuSize
    return i+3

def getERASEB( list, i):
    info.EraseBlock = (int(list[i+0])+int( list[i+1])*256)
    print "ERASE Block = %d" % info.EraseBlock
    return i+1

def getWRITEB( list, i):
    info.WriteBlock = ( int(list[i+0])+int(list[i+1])*256)
    print "WRITE Block = %d" % info.WriteBlock
    return i+1

def getBOOTR( list, i):
    info.BootloaderRevision = ( int(list[i+0])+int(list[i+1])*256)
    print "Bootloader Revision = %x" % info.BootloaderRevision
    return i+1

def getBOOTS( list, i):
    low  = int(list[i+0]) + int(list[i+1])*256
    high = int(list[i+2]) + int(list[i+3])*256
    info.BootStart = (high*65536 + low)
    print "BOOT Start = 0x%x" % info.BootStart
    return i+3

def getDEVDSC( list, i):
    info.DeviceDescription = "".join(map( lambda x: chr(x), list[i : i+20]))
    print "Device Description: %s" % info.DeviceDescription
    return i+20

# Bootloader info field ID's enum 
dBIF = { 
        0: ("ALIGN", skip_align),
        1: ('MCUTYPE', getMCUtype),   # MCU type/family (byte)
        2: ('MCUID',   getMCUid  ),   # MCU ID number ()
        3: ('ERASEBLOCK', getERASEB), # MCU flash erase block size (int)
        4: ('WRITEBLOCK', getWRITEB), # MCU flash write block size (int)
        5: ('BOOTREV',    getBOOTR),  # Bootloader revision (int)
        6: ('BOOTSTART',  getBOOTS),  # Bootloader start address (long)
        7: ('DEVDSC',     getDEVDSC), # Device descriptor (string[20])
        8: ('MCUSIZE',    getMCUSIZE) # MCU flash size (long)
        }
   
def DecodeINFO( list):
    #print list
    size = list[0]
    index = 1
    while index<size:
        #print "index:",index
        try:
            f = dBIF[list[index]]   # find in the dictionary of valid fields
        except:
            print "Field %d at location %d not recognized!" % (list[index], index)
            return
        
        index = f[1](list, index+1)   # call decoding function

        index += 1

#----------------------------------------------------------------------
def Enumerate():
    for d in hid.enumerate(0, 0):
        keys = d.keys()
        print 'manufacturer_string:',d['manufacturer_string']
        print 'vendor_id', d['vendor_id']
        print 'product_id:', d['product_id']
        print

def Check():
    try:
        hid.device( MikroE_vid, Mikromedia_pid)
    except( IOError):
        exit(1)
    exit(0)

def Connect():
    global h
    h = hid.device( MikroE_vid, Mikromedia_pid)
    Info()          # get the device infos
    Boot()          # lock into boot mode

def ConnectLoop():
    print "Connecting..."
    for x in xrange(20): 
        if subprocess.call( ['python', 'HIDBoot.py', '-check']):
            time.sleep(1)
        else:
            break;
        if x == 19: raise Timeout
        print "Reset board and keep checking ..."

    # check succeeded, obtain a handle 
    print "HIDBootloader found!"
    Connect()

def Boot():
    print "Send the BOOT command ..", 
    h.write( [ STX, cmdBOOT])
    r = h.read(2)
    if r[1] == cmdBOOT:
        print "Ready!"

def Info():
    print "Send the INFO command"
    h.write( [ STX, cmdINFO])
    DecodeINFO( h.read(64))

def Erase( block, count):
    # print "Erase: 0x%x " % block
    cmd = [ STX, cmdERASE]
    cmd = extend32bit( cmd, block)   # starting address
    cmd = extend16bit( cmd, count)   # no of  blocks
    h.write( cmd)               
    # print cmd
    r = h.read(2)                    # check reply
    if r != [ STX, cmdERASE]: raise ERASE_ERROR
    
def WriteRow( waddr):
    iaddr = waddr
    count = info.WriteBlock         # number of bytes
    cmd = [ STX, cmdWRITE] 
    cmd = extend32bit( cmd, waddr)
    cmd = extend16bit( cmd, count)
    h.write( cmd)                   # send the command
    cmd=[]

    d = info.dHex
    # test write sequential values
    # for x in xrange( iaddr, iaddr+count):
        # d[x] = x & 0xff

    # pick values out of the hex array
    for x in xrange( iaddr, iaddr+count, 2):
        cmd.extend( [ d[x], d[x+1]])

    # if iaddr == 0:
    #     for x in cmd: print '%02X' % x,
    #     print  
    
    #  do not split, let the lib do it and send multiple (64 byte) HID transactions!
    cmd.insert(0, 0)    # require an alignment??
    h.write(cmd)
    r = h.read(2)
    if r != [ STX, cmdWRITE]: raise WRITE_ERROR

def ReBoot():
    # global h
    print "Rebooting the MCU!"
    h.write( [ STX, cmdREBOOT])
    Close()

def Close():
    # global h
    if h:
        h.close()

def Load( name):
    # init and empty code dictionary 
    info.dHex = None
    try:
        info.dHex = intelhex.IntelHex( name)
        return True
    except:
        return False

def extend16bit( lista, word):
    lista.extend([ word%256, word/256])
    return lista

def extend32bit( lista, long):
    lista = extend16bit( lista, long%65536) 
    lista = extend16bit( lista, long/65536)
    return lista


"""  write test
def Execute( dHex):    
    print "Test erasing the first block at 0x400:07ff, 512 words"
    waddr = getWordsFromBytes( info.EraseBlock)
    # print "waddr", waddr
    Erase( waddr, 1)

    print "Test writing a first block 0x400:047F, 64 words"
    waddr = getWordsFromBytes( info.EraseBlock)
    WriteRow( waddr, dHex)
"""
def EmptyRow( waddr):
    iaddr = waddr
    for x in xrange( info.WriteBlock):
        if info.dHex[ iaddr+x] != 0xff: return False
    return True

def Execute():
    # 1. fix the App reset vector 
    d = info.dHex                               
    a = info.BootStart-4                    # copy it to appReset = BootStart -4
    for x in xrange(4):                     # copy 
        d[a+x] = d[x]

    # 2. fix the reset vector to point to BootStart
    v = extend32bit( [], info.BootStart/2) 
    #     low        goto           high                  Nop
    d[0]=v[0];      d[1]=0xEF;      d[2]=v[1];      d[3]=0xF0+v[2] 
    
    # 3. erase blocks 1..last
    eblk = info.EraseBlock                      # compute erase block size in word
    last = info.BootStart / eblk                # compute number of erase blocks excluding Bootloader    
    print "Erasing ..."
    for x in xrange( 1, last):
        #print "Erase( %d, %d)" % ( x * eblk, 1)
        Erase( x * eblk, 1)                    # erase one at a time

    # 4. program blocks 1..last (if not FF)
    wwblk = info.WriteBlock                     # compute the write block size 
    last = info.BootStart / wwblk               # compute number of write blocks excluding Bootloader
    print "writeBlock= %d, last block = %d" % ( wwblk, last)
    for x in xrange( eblk/wwblk, last):         # write all  rows starting from second erase block
        if not EmptyRow( x * wwblk):            # skip empty rows
            # print "WriteRow( %X)" % (x * wwblk)
            WriteRow( x*wwblk)                  # write to device
            pass

    # 5. erase block 0
    Erase( 0, 1)
    # print "Erase( 0, 1)"

    # 6. program all rows of block 0 
    for x in xrange( eblk/wwblk):          
        WriteRow( x * wwblk)
        # print "WriteRow( %X)" % (x * wwblk)

###################################################################
# main window definition
#
class MainWindow():

    def __init__( self):
        global root
        bgc = 'light gray'
        bgd = 'ghost white'
        root = Tk()
        root.title( "PIC18 Clicker HID Bootloader")
        #root.configure( bg=bgc)
        root.focus_set()
        root.geometry( '+400+100')
        root.protocol( 'WM_DELETE_WINDOW', root.quit) # intercept red button
        root.bind( sequence='<Command-q>', func= lambda e: e.widget.quit)

        root.grid_columnconfigure( 1, minsize=200)
        rowc = 0

        #------- top icon
        rowc += 1
        self.img = PhotoImage(file='mikroBootloader.png')
        Label( root, image=self.img).grid( padx=10, pady=5, columnspan=2, row=rowc, sticky=W)


        #---------- grid
        rowc += 1
        self.MCUType = StringVar()
        self.MCUType.set( 'None')
        Label( root, text="MCU Type:", width=10, bg=bgc).grid( padx=10, pady=5, row=rowc, sticky=W)
        Label( root, textvariable=self.MCUType, width=30, bg=bgd).grid( padx=10, pady=5, row=rowc, column=1, sticky=W)
        Button( root, text='1:Connect', width=15, bg=bgc, command=self.cmdInit).grid(
                padx=10, pady=5, row = rowc, column=2, sticky=N+W)

        rowc += 1
        self.Device = StringVar()
        self.Device.set( 'None')
        Label( root, text="Device:", width=10, bg=bgc).grid( padx=10, pady=5, row=rowc, sticky=W)
        Label( root, textvariable=self.Device, width=30, bg=bgd).grid( padx=10, pady=5, row=rowc, column=1, sticky=W)
        Button( root, text='2: Browse for HEX', width=15, command=self.cmdLoad).grid(
                padx=10, pady=5, row=rowc, column=2)

        rowc += 1
        self.fileHex = StringVar()
        Label( root, text="Hex:", width=10, bg=bgc).grid( padx=10, pady=5, row=rowc, sticky=W)
        Label( root, textvariable=self.fileHex, width=30, bg=bgd).grid( padx=10, pady=5, row=rowc, column=1, sticky=W)
        Button( root, text='3: Begin Uploading', width=15, command=self.cmdProgram).grid(
                padx=10, pady=5, row=rowc, column=2)
        
        #------- bottom row
        #------- status bar --------------------------------------
        rowc += 1
        self.Status = StringVar()
        self.Status.set( 'Uninitialized')
        Label( root, text="Status:", width=10, bg=bgc).grid( padx=10, pady=10, row=rowc, sticky=W)
        Label( root, textvariable=self.Status, width=30, bg=bgd).grid( padx=10, pady=10, row=rowc, column=1, columnspan=2, sticky=W)
        Button( root, text='Quit', width=15, command=root.quit).grid( padx=10, pady=10, row=rowc, column=2, sticky=E+S)

        # check if the file name is loadable
        global dHex
        name = ''
        if len(sys.argv) > 1:
            name = sys.argv[1]
            if not Load( name):
              self.Status.set( "File: %s not found!")
        self.fileHex.set( name)

    #------------------ main commands
    def cmdInit( self):
        if subprocess.call( ['python', 'HIDBoot.py', '-check']):
            # failed to find 
            self.Status.set( "Reset board and try again...")
        else:
            # check succeeded, obtain a handle 
            try:
                Connect()
            except: 
                self.Status.set( "HID Bootloader Found, connection failed")
            else:
                self.Status.set( "HIDBootloader connected!")
                self.Device.set( info.DeviceDescription)
                self.MCUType.set( info.McuType)


    def cmdLoad( self):
        name = askopenfilename()
        if Load(name):
            self.Status.set( "Hex file loaded")
            self.fileHex.set( name)
        else:
            self.Status.set( "Invalid file name")
            self.fileHex.set( '')

    def cmdProgram( self):
        # Execute()
        # try:
            Execute()
        # except:
            # programming error 
            # self.Status.set( "Programming failed")
        # else:
            self.Status.set( "Programming successful")
            ReBoot()
            #root.destroy()

#----------------------------------------------------------------------------

if __name__ == '__main__':
    #discriminate if process is called with the check option
    if len(sys.argv) > 1:
        if sys.argv[1] == '-check':
            Check()

        if sys.argv[1] == '-gui':
            sys.argv.pop(1) # remove the option
            MainWindow()    
            mainloop()
            exit(0)

    # command line mode
    # if a file name is passed
    if len(sys.argv) == 1:
        print "Usage: %s (-gui) file.hex"
        exit(1)
    else:
        name = sys.argv[1]

    # load the hex file provided
    if not Load(name):
        print "File %s not found" % name
        exit(1)

    # loops until gets a connection
    ConnectLoop()

    # run the erase/program sequence
    Execute()

    # 
    ReBoot()


