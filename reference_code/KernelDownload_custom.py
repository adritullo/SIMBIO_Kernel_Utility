import os
import ftplib

def kernelDownload():

    #metakernel_path = r"F:\BEPICOLOMBO_ops\bc_mtp_v433_20260902_001.tm"
    metakernel_path = r"C:\Users\adria\Downloads\bc_nadir_plan_ES.tm"
    outpath = r"F:\BEPICOLOMBO_ops"

    if not os.path.exists(outpath):
        os.mkdir(outpath)
    os.chdir(outpath)

    hostname = r"spiftp.esac.esa.int"
    ftp_server = ftplib.FTP(hostname)
    ftp_server.login()
    ftp_server.encoding = "utf-8"

    filename_path_mk = "data/SPICE/BEPICOLOMBO/kernels/mk"

    filename_path = filename_path_mk.split("mk")[0]
    os.makedirs(filename_path_mk, exist_ok=True)

    # Take meta
    #with open(filename, "wb") as file:
    #    ftp_server.retrbinary(f"RETR {filename}", file.write)

    with open(metakernel_path, "r") as meta:
        metalines = meta.readlines()

        for key, el in enumerate(metalines):
            if "PATH_VALUES" in el:
                pathkey = key
            if "KERNELS_TO_LOAD" in el:
                startkey = key+1
                break
        for key, el in enumerate(metalines[startkey:]):
            if ")" in el:
                endkey = key
                break

    outpath = outpath.replace("\\", "/")
    kernelfolderstring = outpath+"/"+filename_path.removesuffix("/")
    print(kernelfolderstring)



    targetfiles = []
    for el in metalines[startkey:endkey+startkey]:
        if len(el)>1:
            targetfiles.append(el.split("$KERNELS")[1][:-2])
    x = 1
    y = len(targetfiles)
    for el in targetfiles:
        subfolderina = el.split("/")[1]
        os.makedirs(filename_path+"/"+subfolderina, exist_ok=True)

        if not os.path.exists(filename_path+el):
            with open(filename_path+el, "wb") as file:
                # Command for Downloading the file "RETR filename"
                print(f'{x}/{y} - {filename_path+el}')
                ftp_server.retrbinary(f"RETR {filename_path+el}", file.write)
                x +=1
        else:
            print(f'{x}/{y} exists - {filename_path + el}')
            x += 1

    metaname = os.path.basename(metakernel_path)
    new_metakernel_path = f"{outpath}/{filename_path_mk}/{metaname}"
    with open(new_metakernel_path, "w+") as metanew:
        metalines[pathkey] = f"     PATH_VALUES       = ( '{kernelfolderstring}' )\n"
        for el in metalines:
            metanew.write(el)

# Press the green button in the gutter to run the script.
if __name__ == '__main__':

    kernelDownload()
