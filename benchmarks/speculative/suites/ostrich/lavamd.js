// Imported from https://github.com/Sable/Ostrich
// Commit: dd06ca4340ecdbc0a795274d826cb5c034a2b9fe
// Source: n-body-methods/lavamd/js/lavamd.js
// Adaptation: benchmarks/speculative/import_ostrich.py
(function() {
// HBC shells expose Date.now(); SH and V8 also provide performance.now().
var ostrichNow = typeof performance === "undefined"
    ? Date.now : performance.now.bind(performance);
var rv_cpu, qv_cpu, fv_cpu, time0, time1;
// Copyright 2013 the V8 project authors. All rights reserved.
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are
// met:
//
//     * Redistributions of source code must retain the above copyright
//       notice, this list of conditions and the following disclaimer.
//     * Redistributions in binary form must reproduce the above
//       copyright notice, this list of conditions and the following
//       disclaimer in the documentation and/or other materials provided
//       with the distribution.
//     * Neither the name of Google Inc. nor the names of its
//       contributors may be used to endorse or promote products derived
//       from this software without specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
// "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
// LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
// A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
// OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
// SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
// LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
// DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
// THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
// (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
// OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

var commonRandom = (function() {
    var seed = 49734321;
    return function() {
        // Robert Jenkins' 32 bit integer hash function.
        seed = ((seed + 0x7ed55d16) + (seed << 12))  & 0xffffffff;
        seed = ((seed ^ 0xc761c23c) ^ (seed >>> 19)) & 0xffffffff;
        seed = ((seed + 0x165667b1) + (seed << 5))   & 0xffffffff;
        seed = ((seed + 0xd3a2646c) ^ (seed << 9))   & 0xffffffff;
        seed = ((seed + 0xfd7046c5) + (seed << 3))   & 0xffffffff;
        seed = ((seed ^ 0xb55a4f09) ^ (seed >>> 16)) & 0xffffffff;
        return seed;
    };
})();

var commonRandomJS = function () {
    return Math.abs(commonRandom() / 0x7fffffff);
}

/*
 * The MIT License (MIT)
 *
 * Copyright (c) 2014, Erick Lavoie, Faiz Khan, Sujay Kathrotia, Vincent
 * Foley-Bourgon, Laurie Hendren
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */




var NUMBER_PAR_PER_BOX = 100;

function DOT(A,B) {
    return ((A.x)*(B.x)+(A.y)*(B.y)+(A.z)*(B.z));
}

function createArray(creator, size) {
    var arr = [];
    for(var i=0; i<size; i++) {
        arr.push(creator());
    }
    return arr;
}

function nei_str() {
    // neighbor box
    return {
        x: 0, y: 0, z: 0,
        number: 0,
        offset: 0
    };
}

function box_str() {
    // home box
    return {
        x: 0, y: 0, z: 0,
        number: 0,
        offset: 0,
        // neighbor boxes
        nn: 0,
        nei: createArray(nei_str, 26)
    };
}

function space_mem() {
    return {
        v: 0, x: 0, y: 0, z: 0
    }
}

function lavamd(boxes1d) {
    var time0, time1;

    // counters
    var i, j, k, l, m, n, expected_boxes1d = 6;

    // system memory
    var par_cpu = {}, dim_cpu = {}, box_cpu = [], rv_cpu = [], qv_cpu, fv_cpu = [], nh;
    var expectedAns = {
        6: [4144561, 181665, -190914, 140373],
        3: [314053, 36178, 21974, -26368],
        2: [70595, 21913, 11815, 7848]
    }[boxes1d];

    // assign default values
    dim_cpu.cores_arg = 1;
    dim_cpu.boxes1d_arg = boxes1d || 1;

    if(dim_cpu.boxes1d_arg < 0) {
        print("ERROR: Wrong value to -boxes1d parameter, cannot be <=0");
        return;
    }
    print("Configuration used: cores = %d, boxes1d = %d\n", dim_cpu.cores_arg, dim_cpu.boxes1d_arg);

    // INPUTS
    par_cpu.alpha = 0.5;

    // DIMENSIONS
    // total number of boxes
    dim_cpu.number_boxes = dim_cpu.boxes1d_arg * dim_cpu.boxes1d_arg * dim_cpu.boxes1d_arg;

    // how many particles space has in each direction
    dim_cpu.space_elem = dim_cpu.number_boxes * NUMBER_PAR_PER_BOX;

    // BOX
    box_cpu = createArray(box_str, dim_cpu.number_boxes);   // allocate boxes
    // initialize number of home boxes
    nh = 0;

    // home boxes in z direction
    for(i=0; i<dim_cpu.boxes1d_arg; i++){
        // home boxes in y direction
        for(j=0; j<dim_cpu.boxes1d_arg; j++){
            // home boxes in x direction
            for(k=0; k<dim_cpu.boxes1d_arg; k++){

                // current home box
                box_cpu[nh].x = k;
                box_cpu[nh].y = j;
                box_cpu[nh].z = i;
                box_cpu[nh].number = nh;
                box_cpu[nh].offset = nh * NUMBER_PAR_PER_BOX;

                // initialize number of neighbor boxes
                box_cpu[nh].nn = 0;

                // neighbor boxes in z direction
                for(l=-1; l<2; l++){
                    // neighbor boxes in y direction
                    for(m=-1; m<2; m++){
                        // neighbor boxes in x direction
                        for(n=-1; n<2; n++){
                            // check if (this neighbor exists) and (it is not the same as home box)
                            if((((i+l)>=0 && (j+m)>=0 && (k+n)>=0)==true && ((i+l)<dim_cpu.boxes1d_arg && (j+m)<dim_cpu.boxes1d_arg && (k+n)<dim_cpu.boxes1d_arg)==true)   &&
                                    (l==0 && m==0 && n==0)==false){

                                // current neighbor box
                                box_cpu[nh].nei[box_cpu[nh].nn].x = (k+n);
                                box_cpu[nh].nei[box_cpu[nh].nn].y = (j+m);
                                box_cpu[nh].nei[box_cpu[nh].nn].z = (i+l);
                                box_cpu[nh].nei[box_cpu[nh].nn].number = (box_cpu[nh].nei[box_cpu[nh].nn].z * dim_cpu.boxes1d_arg * dim_cpu.boxes1d_arg) +
                                                                            (box_cpu[nh].nei[box_cpu[nh].nn].y * dim_cpu.boxes1d_arg) +
                                                                             box_cpu[nh].nei[box_cpu[nh].nn].x;
                                box_cpu[nh].nei[box_cpu[nh].nn].offset = box_cpu[nh].nei[box_cpu[nh].nn].number * NUMBER_PAR_PER_BOX;

                                // increment neighbor box
                                box_cpu[nh].nn = box_cpu[nh].nn + 1;
                            }
                        } // neighbor boxes in x direction
                    } // neighbor boxes in y direction
                } // neighbor boxes in z direction
                // increment home box
                nh = nh + 1;
            } // home boxes in x direction
        } // home boxes in y direction
    } // home boxes in z direction

    //  PARAMETERS, DISTANCE, CHARGE AND FORCE
    // input (distances)
    rv_cpu = createArray(space_mem, dim_cpu.space_elem); //(FOUR_VECTOR*)malloc(dim_cpu.space_mem);
    for(i=0; i<dim_cpu.space_elem; i=i+1){
        rv_cpu[i].v = (commonRandom()%10 + 1) / 10.0;        // get a number in the range 0.1 - 1.0
        rv_cpu[i].x = (commonRandom()%10 + 1) / 10.0;        // get a number in the range 0.1 - 1.0
        rv_cpu[i].y = (commonRandom()%10 + 1) / 10.0;        // get a number in the range 0.1 - 1.0
        rv_cpu[i].z = (commonRandom()%10 + 1) / 10.0;        // get a number in the range 0.1 - 1.0
    }

    // input (charge)
    qv_cpu = new Float64Array(dim_cpu.space_elem); // (fp*)malloc(dim_cpu.space_mem2);
    for(i=0; i<dim_cpu.space_elem; i=i+1){
        qv_cpu[i] = (commonRandom()%10 + 1) / 10;            // get a number in the range 0.1 - 1.0
    }

    // output (forces)
    fv_cpu = createArray(space_mem, dim_cpu.space_elem); //(FOUR_VECTOR*)malloc(dim_cpu.space_mem);

    time0 = ostrichNow();

    kernel_cpu(par_cpu, dim_cpu, box_cpu, rv_cpu, qv_cpu, fv_cpu);

    var sum = space_mem();
    if (expectedAns !== undefined) {
        for(i=0; i<dim_cpu.space_elem; i=i+1) {
            sum.v += fv_cpu[i].v;
            sum.x += fv_cpu[i].x;
            sum.y += fv_cpu[i].y;
            sum.z += fv_cpu[i].z;
        }
        if(Math.round(sum.v) != expectedAns[0] || Math.round(sum.x) != expectedAns[1] || Math.round(sum.y) != expectedAns[2] || Math.round(sum.z) != expectedAns[3]) {
            print("Expected: [" + expectedAns[0] + ", " + expectedAns[1] + ", " + expectedAns[2] + ", " + expectedAns[3] + "]");
            throw new Error("Got: [" + sum.v + ", " + sum.x + ", " + sum.y + ", " + sum.z + "]");
        }
    } else {
        print("WARNING: no self-checking for input size of '%d'\n", dim_cpu.boxes1d_arg);
    }

    time1 = ostrichNow();
    print("Total time: " + (time1-time0) / 1000 + " s");
    return { status: 1,
             options: "lavamd(" + boxes1d + ")",
             time: (time1 - time0) / 1000 };
}

function kernel_cpu(par, dim, box, rv, qv, fv) {
    var alpha, a2;                      // parameters
    var i, j, k, l;                     // counters
    var first_i, pointer, first_j;      // neighbor box
    // common
    var r2, u2, fs, vij, fxij, fyij, fzij;
    var d;

    //  INPUTS
    alpha = par.alpha;
    a2 = 2.0*alpha*alpha;
    // PROCESS INTERACTIONS

    for(l=0; l<dim.number_boxes; l=l+1) {
        // home box - box parameters
        first_i = box[l].offset;

        //  Do for the # of (home+neighbor) boxes
        for(k=0; k<(1+box[l].nn); k++) {
            //  neighbor box - get pointer to the right box
            if(k==0) {
                pointer = l;    // set first box to be processed to home box
            } else {
                pointer = box[l].nei[k-1].number;   // remaining boxes are neighbor boxes
            }

            first_j = box[pointer].offset;

            for(i=0; i<NUMBER_PAR_PER_BOX; i=i+1) {
                for(j=0; j<NUMBER_PAR_PER_BOX; j=j+1) {
                    r2 = rv[first_i+i].v + rv[first_j+j].v - DOT(rv[first_i+i],rv[first_j+j]);
                    u2 = a2*r2;
                    vij= Math.exp(-u2);
                    fs = 2.*vij;
                    var dx = rv[first_i+i].x  - rv[first_j+j].x;
                    var dy = rv[first_i+i].y  - rv[first_j+j].y;
                    var dz = rv[first_i+i].z  - rv[first_j+j].z;
                    fxij=fs*dx;
                    fyij=fs*dy;
                    fzij=fs*dz;

                    // forces
                    fv[first_i+i].v +=  qv[first_j+j]*vij;
                    fv[first_i+i].x +=  qv[first_j+j]*fxij;
                    fv[first_i+i].y +=  qv[first_j+j]*fyij;
                    fv[first_i+i].z +=  qv[first_j+j]*fzij;
                }
            }
        }
    }
}

function runLavaMD(boxes1d) {
    return lavamd(boxes1d);
}

const OSTRICH_ARGS = [3];
var result = runLavaMD(OSTRICH_ARGS[0]);
if (!result || result.status !== 1 ||
    !Number.isFinite(result.time) || result.time <= 0) {
    throw new Error("Invalid benchmark result");
}
print("Time: " + result.time * 1000);
})();
