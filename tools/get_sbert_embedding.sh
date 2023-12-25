MODEL=$1
TASK=$2
K=16

# python3 tools/get_sbert_embedding.py --sbert_model $MODEL --task SST-2 sst-5 mr cr mpqa subj trec CoLA MRPC QQP STS-B MNLI SNLI QNLI RTE
# python3 tools/get_sbert_embedding.py --sbert_model $MODEL --seed 42 --do_test --task SST-2 sst-5 mr cr mpqa subj trec CoLA MRPC QQP STS-B MNLI SNLI QNLI RTE

python3 tools/get_sbert_embedding.py --sbert_model $MODEL --task $TASK
python3 tools/get_sbert_embedding.py --sbert_model $MODEL --seed 42 --do_test --task $TASK

for seed in 13 21 87 100
do
    # for task in SST-2 sst-5 mr cr mpqa subj trec CoLA MRPC QQP STS-B MNLI SNLI QNLI RTE
    for task in ar-en-sa ar-ner-corp my-ar-sa
    do
        cp data/k-shot/$task/$K-42/test_sbert-$MODEL.npy  data/k-shot/$task/$K-$seed/
    done

    # cp data/k-shot/MNLI/$K-42/test_matched_sbert-$MODEL.npy  data/k-shot/MNLI/$K-$seed/
    # cp data/k-shot/MNLI/$K-42/test_mismatched_sbert-$MODEL.npy  data/k-shot/MNLI/$K-$seed/
done
