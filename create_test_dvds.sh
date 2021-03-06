#! /bin/bash

set -e

if ! test -d co; then
	echo "you need to call this in a directory with a co directory containting osc checkouts with the staging prjs" 
	exit 1
fi

# give it target Factory by default then will not breaks current operation
if [ $# -eq 0 ]; then
    targets='Factory'
else
    targets=$@
fi

CODIR=$PWD
SCRIPTDIR=`dirname "$0"`

function regenerate_pl() {
    prj=$1
    shift;

    target=$1
    shift;

    suffix=$1
    shift;
    
    tcfile=tc.$target.$suffix.$1
    : > $tcfile
    for i in "$@"; do
	echo "repo $i 0 solv $i.solv" >> $tcfile
    done
    cat $SCRIPTDIR/create_test_$target\_dvd-$suffix.testcase >> $tcfile

    out=$(mktemp)
    testsolv -r $tcfile > $out
    if grep ^problem $out ; then
         return
    fi
    sed -i -e 's,^install \(.*\)-[^-]*-[^-]*\.[^-\.]*@.*,\1,' $out
    
    p=$(mktemp)
    tdir=$CODIR/co/$prj/Test-DVD-x86_64
    if [ ! -d "$tdir" ]; then
	mkdir -p "$tdir"
	osc co -o "$tdir" "$prj" Test-DVD-x86_64
    fi
    pushd $tdir > /dev/null
    osc up
    popd > /dev/null
    sed -n -e '1,/BEGIN-PACKAGELIST/p' $tdir/PRODUCT-x86_64.kiwi > $p
    for i in $(cat $out); do
	echo "<repopackage name='$i'/>" >> $p
    done
    sed -n -e '/END-PACKAGELIST/,$p' $tdir/PRODUCT-x86_64.kiwi >> $p
    xmllint --format $p -o $tdir/PRODUCT-x86_64.kiwi
    rm $p $out
    pushd $tdir > /dev/null
    if ! cmp -s .osc/PRODUCT-x86_64.kiwi PRODUCT-x86_64.kiwi; then
      osc ci -m "auto update"
    fi
    popd > /dev/null
}

function sync_prj() {
    prj=$1
    dir=$2
    mkdir -p $dir
    perl $SCRIPTDIR/bs_mirrorfull --nodebug https://build.opensuse.org/build/$prj/x86_64 $dir
    if [ "$dir" -nt "$dir.solv" ]; then
	    local start=$SECONDS
	    rpms2solv $dir/*.rpm > $dir.solv
	    echo "creating ${dir}.solv took $((SECONDS-$start))s"
    fi
}

function start_creating() {
    for target in "$@"; do
        # Rings part
        sync_prj openSUSE:$target:Rings:0-Bootstrap/standard/ $target-bootstrap
        sync_prj openSUSE:$target:Rings:1-MinimalX/standard $target-minimalx

        regenerate_pl openSUSE:$target:Rings:1-MinimalX $target 1 $target-bootstrap $target-minimalx

        sync_prj openSUSE:$target:Rings:2-TestDVD/standard $target-testdvd
        regenerate_pl openSUSE:$target:Rings:2-TestDVD $target 2 $target-bootstrap $target-minimalx $target-testdvd

	echo "Checking $target:A"
        # Staging A part
        sync_prj openSUSE:$target:Staging:A/standard staging_$target:A
        regenerate_pl "openSUSE:$target:Staging:A" $target 1 staging_$target:A

        sync_prj openSUSE:$target:Staging:A:DVD/standard staging_$target:A-dvd
        regenerate_pl "openSUSE:$target:Staging:A:DVD" $target 2 staging_$target:A staging_$target:A-dvd

        projects=$(osc api /search/project/id?match="starts-with(@name,\"openSUSE:$target:Staging\")" | grep name | cut -d\' -f2)
        for prj in openSUSE:$target:Rings:2-TestDVD $projects; do
            l=$(echo $prj | cut -d: -f4)
            if [[ $prj =~ ^openSUSE.+:[A-Z]$ ]]; then
                # no need for A, already did
                if [ $l != "A" ]; then
                    echo "Checking $target:$l"
                    sync_prj openSUSE:$target:Staging:$l/bootstrap_copy "staging_$target:$l-bc"
                    sync_prj openSUSE:$target:Staging:$l/standard staging_$target:$l
                    regenerate_pl "openSUSE:$target:Staging:$l" $target 1 "staging_$target:$l-bc" staging_$target:$l
                fi
            fi

            if [[ ( $prj =~ :DVD ) || ( $prj =~ Rings:2-TestDVD ) ]]; then
                perl $SCRIPTDIR/rebuildpacs.pl $prj standard x86_64
            fi

            if [[ $prj =~ ^openSUSE.+:[A-Z]:DVD$ ]]; then
                # no need for A, already did
                if [ $l != "A" ]; then
                    sync_prj openSUSE:$target:Staging:$l:DVD/standard "staging_$target:$l-dvd"
                    regenerate_pl "openSUSE:$target:Staging:$l:DVD" $target 2 "staging_$target:$l-bc" staging_$target:$l "staging_$target:$l-dvd"
                fi
            fi
        done
    done
}

# call main function
start_creating $targets

