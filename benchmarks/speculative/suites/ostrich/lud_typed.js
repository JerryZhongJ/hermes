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

Math.commonRandom = (function() {
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

Math.commonRandomJS = function () {
    return Math.abs(Math.commonRandom() / 0x7fffffff);
}

/*
Math.commonRandom = (function() {
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

Math.commonRandomJS = function () {
    return Math.abs(Math.commonRandom() / 0x7fffffff);
}
*/


function randomMatrix(matrix, max, min) {
    for(var i = 0; i < matrix.length; ++i) {
	//matrix[i] = Math.random()*(max-min) + min;
        matrix[i] = Math.abs(Math.commonRandomJS()) * (max-min) + min;
    }
}

function printM(a, m, n){
    console.log("Printing Matrix:");
    for(var i =0; i<m; ++i){
        console.log("[" +
                    Array.prototype.join.call(Array.prototype.slice.call(a, i*m, i*m + n), ",") +
                    "]");
    }
}

function lud(size) {
    size = size|0;
    var i=0,j=0,k=0;
    var sum=0.0;

    for(i=0; (i|0)<(size|0); (++i)|0) {
	for(j=i|0; (j|0)<(size|0); (++j)|0) {
	    sum = +matrix[((((i|0)*(size|0))+j)|0)];
	    for (k=0; (k|0)<(i|0); (++k)|0) {
		sum = +(sum - +(+matrix[((i*size)|0+k)|0] * +matrix[((k*size)|0+j)|0]));
	    }

	    matrix[((i*size)|0+j)|0] = +sum;
	}

	for (j=(i+1)|0; (j|0)<(size|0); (j++)|0) {
	    sum=+matrix[((j*size)|0+i)|0];
	    for (k=0; (k|0)<(i|0); (++k)|0) {
		sum = +(sum - +(+matrix[((j*size)|0+k)|0] * +matrix[((k*size)|0+i)|0]));
	    }
	    matrix[((j*size)|0+i)|0] = +(+sum / +matrix[((i*size)|0+i)|0]);
	}
    }
}

var matrix;

function ludRun(size) {
    matrix = new Float64Array(size*size);
    randomMatrix(matrix, 0, 10000);
    console.log("Matrix of size: " + size);
    var t1 = performance.now();
    lud(size);
    var t2 = performance.now();
    console.log("Time consumed typed (s): " + ((t2-t1) / 1000).toFixed(6));
    return { status: 1,
             options: "ludRun(" + size + ")",
             time: (t2-t1) / 1000 };
}


// Static Hermes benchmark runner: fixed params, timed with performance.now
var __performance = globalThis.performance ?? (globalThis.performance = {});
__performance.now ??= Date.now;
var __start = __performance.now();
ludRun( 384 );
var __end = __performance.now();
print( "Time: " + Math.round( __end - __start ) );
