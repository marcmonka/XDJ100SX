var XDJ100SX = {};
XDJ100SX.currentMode = 0;

//Init

XDJ100SX.init = function(){
    engine.setValue("[Channel2]", "filterLowKill", 1); //This is the default mode
    engine.setValue("[Channel2]", "filterMidKill", 0);
    engine.setValue("[Channel2]", "filterHighKill", 0);
    engine.setValue("[Channel3]", "filterLowKill", 0); 
    engine.setValue("[Channel3]", "filterMidKill", 0);
    engine.setValue("[Channel3]", "filterHighKill", 0);
}

//Shutdown

XDJ100SX.shutdown = function(){
    //Turn off all leds

    var LedNotes = [0x41, 0x3D, 0x40, 0x3E, 0x3F];
    for (var i = 0; i < LedNotes.length; i++) {
        var note = LedNotes[i];
        
        // Enviem el missatge Note Off (status, nota, velocitat 0)
        midi.sendShortMsg(0x80, note, 0x00);
    }
};




//Jog Wheel
XDJ100SX.JogWheelEnabled = false;

XDJ100SX.nudgeWheelTurn = function (channel, control, value, status, group) {
    
    XDJ100SX.lastJogMoveTime = Date.now();
    var newValue = value - 64;
    
    var deckNumber = script.deckFromGroup(group);

    if (engine.isScratching(deckNumber)) {
        engine.scratchTick(deckNumber, newValue); // Scratch!
        XDJ100SX.JogWheelEnabled = false;

    } else {
        engine.setValue(group, 'jog', newValue); // Pitch bend
        XDJ100SX.JogWheelEnabled = true;
    }

    
};



//Search buttons

XDJ100SX.searchButton = function (channel, control, value, status, group){
    const NOTE_SEARCH_FORWARD = 0x43;
    const NOTE_SEARCH_BACKWARD = 0x42;

     var isJogActive = (Date.now() - XDJ100SX.lastJogMoveTime < 100);


    //Si moc el jog wheel
    if (isJogActive){
        if (control === NOTE_SEARCH_FORWARD) {
       
            if (value === 127) { // Si s'ha premut (Note On)
                script.triggerControl(group,"rateSearch_up", 1);
            } 
            if (value === 0){
                script.triggerControl(group,"rateSearch_set_zero", 1);

            }
        } 
        else if (control === NOTE_SEARCH_BACKWARD){
            if(value === 127){
                script.triggerControl(group,"rateSearch_down",1);

            }
            if(value === 0){
                script.triggerControl(group,"rateSearch_set_zero",1);

            }
        }

    }
  //Si no moc el jog wheel
    else{
        if (control === NOTE_SEARCH_FORWARD) {
       
            if (value === 127) { // Si s'ha premut (Note On)
                script.triggerControl(group,"rateSearch_up_small", 1);
            } 
            if (value === 0){
                script.triggerControl(group,"rateSearch_set_zero", 1);

            }
        } 
        else if (control === NOTE_SEARCH_BACKWARD){
            if(value === 127){
                script.triggerControl(group,"rateSearch_down_small",1);

            }
            if(value === 0){
                script.triggerControl(group,"rateSearch_set_zero",1);

            }
        }


    }

};


//Pitch ranges
XDJ100SX.rateRanges = [0.08, 0.10, 0.16, 0.24, 0.50]; //valors de rang del pitch
XDJ100SX.currentRange = 0;

//Beat Jump ranges
XDJ100SX.BeatJumpRanges = [4, 8, 16, 32, 64, 128];
XDJ100SX.currentBeatJumpRange = 3;


//Shift

XDJ100SX.shiftPressed = false;
XDJ100SX.shift = function(channel,control,value,status,group){
    if(value === 127){
        XDJ100SX.shiftPressed = true;
    }
    else{
        XDJ100SX.shiftPressed = false;
    }
};

//Master Tempo & Tempo Range

XDJ100SX.key = function (channel, control, value, status, group){
    if(XDJ100SX.shiftPressed){
        if (value){
        XDJ100SX.currentRange++;
        if(XDJ100SX.currentRange >= XDJ100SX.rateRanges.length){
            XDJ100SX.currentRange = 0;
        }
        engine.setValue(group, "rateRange", XDJ100SX.rateRanges[XDJ100SX.currentRange]);
        }
    }
    else{
        script.toggleControl(group, "keylock", 100);
    }
};

//Button Mode

XDJ100SX.buttonMode = function (channel, control, value, status, group) {
    
    if (value > 0) {
        // Go to next mode
        XDJ100SX.currentMode = (XDJ100SX.currentMode + 1) % 6;

        // Set all to 0
        engine.setValue("[Channel2]", "filterLowKill", 0);
        engine.setValue("[Channel2]", "filterMidKill", 0);
        engine.setValue("[Channel2]", "filterHighKill", 0);
         engine.setValue("[Channel3]", "filterLowKill", 0);
        engine.setValue("[Channel3]", "filterMidKill", 0);
        engine.setValue("[Channel3]", "filterHighKill", 0);

        // Enable the current one
        if (XDJ100SX.currentMode === 0) {
            engine.setValue("[Channel2]", "filterLowKill", 1); //Mode 1
        } else if (XDJ100SX.currentMode === 1) {
            engine.setValue("[Channel2]", "filterMidKill", 1); //Mode 2
        } else if (XDJ100SX.currentMode === 2){ 
            engine.setValue("[Channel2]", "filterHighKill", 1); //Mode 3
        }
        else if (XDJ100SX.currentMode === 3){ 
            engine.setValue("[Channel3]", "filterLowKill", 1); //Mode 4
        }
        else if (XDJ100SX.currentMode === 4){ 
            engine.setValue("[Channel3]", "filterMidKill", 1); //Mode 5
        }
        else{ 
            engine.setValue("[Channel3]", "filterHighKill", 1); //Mode 6
        }
    }
};



//Buttons (Jet, Zip, Wah)

//Mode 0 = Hot Cue A, B, C
//Mode 1 = Hot Cue D, E, F
//Mode 2 = Hot Cue G, H
//Mode 3 = Loop Roll 1/8, Loop Roll 1/4, Loop Roll 1/2
//Mode 4 = Beat Jump Length Back, Beat Jump Length Forward, Change Beat Jump Length
//Mode 5 = Key Shift -, Key Shift +, Key Reset

XDJ100SX.button = function(buttonNumber){
    return function (channel, control, value, status, group){
        if(value === 127){

            //Hot Cue A, B, C
            if(XDJ100SX.currentMode === 0){
                if(XDJ100SX.shiftPressed){
                    engine.setValue(group, "hotcue_" + buttonNumber + "_clear", 1);
                }
                else{
                    engine.setValue(group, "hotcue_" + buttonNumber + "_activate", 1);
                }
            }
            // Hot Cue D, E, F
            if(XDJ100SX.currentMode === 1){
                
                    var mode = buttonNumber + 3;

                    if(XDJ100SX.shiftPressed){
                    engine.setValue(group, "hotcue_" + mode + "_clear", 1);
                    }
                    else{
                    engine.setValue(group, "hotcue_" + mode + "_activate", 1);
                    }
            }
            // Hot Cue G, H
            if(XDJ100SX.currentMode === 2){
                
                    var mode = buttonNumber + 6;

                    if(XDJ100SX.shiftPressed){
                    engine.setValue(group, "hotcue_" + mode + "_clear", 1);
                    }
                    else{
                    engine.setValue(group, "hotcue_" + mode + "_activate", 1);
                    }
            }

            //Loop Roll
            if (XDJ100SX.currentMode === 3){
                if (buttonNumber === 1){
                    engine.setValue(group, "beatlooproll_0.125_activate", 1);
                }
                if (buttonNumber === 2){
                     engine.setValue(group, "beatlooproll_0.25_activate", 1);
                }
                else if(buttonNumber === 3){
                    engine.setValue(group,"beatlooproll_0.5_activate", 1);
                }
            }

            //BeatJump
            if (XDJ100SX.currentMode === 4){
                if (buttonNumber === 1){
                    engine.setValue(group, "beatjump_" + XDJ100SX.BeatJumpRanges[XDJ100SX.currentBeatJumpRange] + "_backward", 1);
                }
                if (buttonNumber === 2){
                     engine.setValue(group, "beatjump_" + XDJ100SX.BeatJumpRanges[XDJ100SX.currentBeatJumpRange] + "_forward", 1);
                }
                else if(buttonNumber === 3){
                    XDJ100SX.currentBeatJumpRange++;
                    if(XDJ100SX.currentBeatJumpRange >= XDJ100SX.BeatJumpRanges.length){
                        XDJ100SX.currentBeatJumpRange = 0;
                    }
                    engine.setValue(group,"beatjump_size", XDJ100SX.BeatJumpRanges[XDJ100SX.currentBeatJumpRange]);
                }
            }
            
            //Key Shift
            if(XDJ100SX.currentMode === 5){
                if (buttonNumber === 1){
                    engine.setValue(group, "pitch_down", 1);
                }
                if (buttonNumber === 2){
                     engine.setValue(group, "pitch_up", 1);
                }
                else if(buttonNumber === 3){
                    engine.setValue(group,"reset_key", 1);
                }
            }



        }
        //When release button (Note Off) (Must to disable Loop Roll)
        else if(value === 0){
            if (XDJ100SX.currentMode === 3){
                if (buttonNumber === 1){
                    engine.setValue(group, "beatlooproll_0.125_activate", 0);
                }
                if (buttonNumber === 2){
                     engine.setValue(group, "beatlooproll_0.25_activate", 0);
                }
                else if(buttonNumber === 3){
                    engine.setValue(group,"beatlooproll_0.5_activate", 0);
                }

            }
        }
    }
};

XDJ100SX.button1 = XDJ100SX.button(1);
XDJ100SX.button2 = XDJ100SX.button(2);
XDJ100SX.button3 = XDJ100SX.button(3);


//BOTÓ CUE: shift + cue torna a l'inici

XDJ100SX.cue = function (channel, control, value, status, group){
    if(value === 127){
        if(XDJ100SX.shiftPressed){
            engine.setValue(group, "start_stop", 1);
        }
        else{
            engine.setValue(group, "cue_cdj",1);
        }
    }
    else{
            engine.setValue(group, "cue_cdj",0);
    }
}



//Pitch Slider

XDJ100SX.pitchLast = 0;

XDJ100SX.pitch = function (channel, control, value, status, group) {
    var midiMin = 0;
    var midiMax = 127;
    var midiCenter = 60; // ajusta segons el teu fader real

    // Normalitza directament a -1..+1
    var normalized;
    if (value >= midiCenter) {
        normalized = (value - midiCenter) / (midiMax - midiCenter);
    } else {
        normalized = (value - midiCenter) / (midiCenter - midiMin);
    }
    normalized = -normalized;

    // Deadzone per evitar soroll
    var threshold = 0.015;
    if (Math.abs(normalized - XDJ100SX.pitchLast) > threshold) {
        XDJ100SX.pitchLast = normalized;
        engine.setValue(group, "rate", normalized);
    }
};


//Browse Encoder (scroll + canviar vista)
XDJ100SX.browseDown = function(channel, control, value, status, group) {
    if (value === 127) {
        // llegim el control actual
        var currentTab = engine.getValue("[Tab]", "current"); 
        if (currentTab === 0) { // 0 = overview
            engine.setValue("[Channel1]", "waveform_zoom_down", 1); // 1 = library
        }
        // Enviem moviment al browser
        engine.setValue("[Library]", "MoveDown", 1);
    }
};

XDJ100SX.browseUp = function(channel, control, value, status, group) {
    if (value === 127) {
        var currentTab = engine.getValue("[Tab]", "current");
        if (currentTab === 0) { 
            engine.setValue("[Channel1]", "waveform_zoom_up", 1);
        }
        engine.setValue("[Library]", "MoveUp", 1);
    }
};

//Botó LOAD (carregar cançó + tornar a vista overview o vista anterior)
XDJ100SX.loadTrack = function(channel, control, value, status, group){
    if (value === 127){
        var currentTab = engine.getValue("[Tab]", "current");
        var currentLibrary = engine.getValue("[Sidebar]", "sidebar_visible");
        if (currentTab === 1 && currentLibrary === 0){
            engine.setValue(group,"LoadSelectedTrack", 1);
            engine.setValue("[Tab]", "current", 0); //overview
        }
        if (currentTab === 1 && currentLibrary === 1){
            engine.setValue("[Sidebar]", "sidebar_visible", 0); //overview
            engine.setValue("[Library]", "GoToItem", 2); //salta't el search i focus a llibreria

        }

}
};

//Botó BACK

XDJ100SX.backButton = function(channel, control, value, status, group){
    if(value === 127){
        var currentTab = engine.getValue("[Tab]", "current");
        var currentLibrary = engine.getValue("[Sidebar]", "sidebar_visible");
        if (currentTab === 0){
            engine.setValue("[Tab]", "current", 1); //library
            engine.setValue("[Library]", "focused_widget",3); //salta't el search i focus a les cançons
        }
        if(currentTab === 1 && currentLibrary == 0){ //llista principal
            engine.setValue("[Sidebar]","sidebar_visible",1);
            engine.setValue("[Library]", "focused_widget", 2); //salta't el search i focus a les carpetes

        }
        if(currentTab === 1 && currentLibrary == 1){ //llistes de reproducció
            engine.setValue("[Sidebar]","sidebar_visible",0);
            engine.setValue("[Library]", "focused_widget", 3); //salta't el search i focus a les cançons
        }
        }
        
    
};


