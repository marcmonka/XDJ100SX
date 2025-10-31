#include "usb_names.h"

#define MIDI_NAME   {'X','D','J','1','0','0','S','X'}
#define MIDI_NAME_LEN  8

struct usb_string_descriptor_struct usb_string_product_name = {
        2 + MIDI_NAME_LEN * 2,
        3,
        MIDI_NAME
};
